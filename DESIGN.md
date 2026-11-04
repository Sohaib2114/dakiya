# Dakiya design note

Scope: how the service stays up on Dakiya's two servers and in the partner's private cloud,
how releases move at ten client deployments, and what we alert on.

## 1. High availability

### What fails first

| Part | Today | What happens when it fails |
|---|---|---|
| PostgreSQL | one instance | **Single point of failure.** Reads (`GET /parcels`) fail, the worker cannot write. Scans are still accepted and wait in Redis. |
| Redis | one instance, queue on disk (AOF) | `POST /scans` fails: depots and riders cannot send scans. Already-queued scans survive a restart. |
| Server / node | everything on one host | Everything stops. |
| Worker | `BRPOP` then insert | If it dies between the two, that one scan is lost (app code, see README findings). Backlog grows while it is down but nothing else breaks. |
| API | stateless | Any replica can serve; cheapest part to make redundant. |

So the order is: **the database first, then Redis, then the single server**. The API is the least of the problems.

### Dakiya's two servers

Two servers is not enough for a safe Kubernetes control plane (etcd needs three for a majority), and a
two-node cluster that loses one node can lose the whole cluster. Options I would put to the team:

1. **Recommended: k3s with an external datastore, or a third small VM as the third server.** A cheap 2 GB VM
   (or one in the office) is enough to hold quorum. Then both big servers run workloads and either can fail.
2. **No Kubernetes on-prem: Docker Compose on both servers** behind a load balancer (keepalived floating IP or
   the existing router). The API runs on both; PostgreSQL primary on server A with a streaming replica on server B;
   Redis on A with AOF. Failover of the database is a documented manual step (promote the replica, move the IP).
   Simple, but failover is manual and takes minutes.

Either way:
- **PostgreSQL**: primary + streaming replica on the other server (CloudNativePG operator on Kubernetes, or plain
  `pg_basebackup` replication with Compose), nightly `pg_dump` + WAL archive to storage *off* both servers. A backup
  that lives on the same two machines is not a backup.
- **Redis**: AOF on (done). For more, Redis Sentinel with 3 sentinels; for a queue this small I would rather move
  the queue into PostgreSQL later than run Sentinel.
- **API**: 2+ replicas, spread across the two nodes (`topologySpreadConstraints`), PodDisruptionBudget (done).

### Partner's private cloud

Their cloud gives us what Dakiya's servers do not: three availability zones and a managed database.
- Their managed PostgreSQL (multi-AZ) instead of our StatefulSet: the chart gets `postgres.enabled: false` and
  an external host. Backups and failover become their cloud's job.
- Their Kubernetes (3+ nodes across zones), API replicas spread across zones, PDB.
- No inbound access: their Argo CD **pulls** from git and their own registry mirror (section 2), nothing connects in.

### Upgrades without downtime

- **API / worker**: rolling update with `maxUnavailable: 0`: a new pod must pass `/readyz` before an old one stops.
  The PDB keeps one API pod during node drains. Workers can stop at any time; scans wait in Redis.
- **Database schema**: only backward-compatible changes in one release (add a column, never rename or drop in the
  same release), so old and new API pods work side by side during the rollout. Destructive changes go in a later release.
- **PostgreSQL major version** (for example 17 → 18): planned, never automatic. Dependabot is told to skip major
  database versions after it proposed 18 and our e2e job showed it does not start on the old data. Done with
  `pg_upgrade` or dump/restore onto the replica, then switch over.
- **Rollback**: revert the tag change in git; Argo CD deploys the previous image. Every image is tagged with its commit.

## 2. Branch and environment model at ten client deployments

**One repo, one branch (`main`), one folder per deployment:**

```
deploy/helm/dakiya/              the chart (same for everyone)
deploy/envs/staging/values.yaml  CI writes the tag here after every green build
deploy/envs/production/values.yaml
deploy/envs/partner-retail/values.yaml
deploy/envs/<client-n>/values.yaml   a new client = a new folder
```

The ApplicationSet creates one Argo CD Application per folder. Branches per environment were rejected: merging
between ten long-lived branches drifts and nobody knows what differs. Folders make the difference visible in one diff.

- **How a fix reaches every client.** The fix is merged to `main`, CI builds `sha-abc1234`, staging gets it
  automatically. Promotion is one pull request that sets `image.tag: sha-abc1234` in every client folder that should
  get it. For a security fix that is all ten folders in one PR; normally a small script opens one PR per client so each
  can be reviewed and merged on its own schedule. Production first, then partners.
- **How one client stays on an older version.** Its folder keeps the old tag; nothing else to do. Today the chart
  itself comes from `main` for everyone, which is fine while all clients run the same chart. Before ten clients I would
  **publish the chart as a versioned OCI artifact** (`ghcr.io/.../charts/dakiya:0.3.0`) and let each folder pin
  both the chart version and the image tag. Then an old client is fully frozen, including templates.
- **How updates reach a site with no inbound access.** Nothing pushes into the partner. The partner runs its own Argo
  CD inside its network, with **outbound-only** access to: this git repo (read-only deploy key / fine-grained token,
  only its own folder via an AppProject), and the image registry (read-only token). If they allow no internet at all,
  CI also pushes the signed images to a registry they mirror (Harbor or their cloud registry), and they mirror the
  git repo; their Argo CD reads the mirror. Either way they control when changes come in and we never need a VPN
  into their network.
- **Who can change what.** Branch protection on `main` (require a pull request and green CI), and `CODEOWNERS` so a
  change under `deploy/envs/production/` or a partner folder needs approval from the release owner. CI's bot may only
  write to `deploy/envs/staging/`.

## 3. Five alerts

Metrics from Prometheus (kube-state-metrics, api request metrics, postgres_exporter, redis_exporter), alerts
through Alertmanager to the on-call phone. Thresholds are a starting point, tuned after two weeks of real traffic.

| # | Alert | Threshold | Why it matters |
|---|---|---|---|
| 1 | **API error rate** | 5xx > 2% of requests for 5 min | customers and depots get errors; first sign of most outages |
| 2 | **Scan backlog / worker lag** | Redis `scans` list > 1,000 items, or growing for 10 min, or no worker running for 2 min | scans accepted but parcel status not updated: customers see old status |
| 3 | **PostgreSQL down or full** | not ready for 1 min, or disk > 80% (page at 90%) | the single point of failure; a full disk stops all writes |
| 4 | **API latency** | p95 of `GET /parcels/{id}` > 500 ms for 10 min | slow before it is broken: usually the database |
| 5 | **Pods crash-looping / not ready** | any dakiya pod restarted > 3 times in 15 min, or a Deployment below desired replicas for 10 min | bad release or bad config; tells us to roll back |

Plus one that is not about the app but would have saved this project: **backup check**, last successful database
backup older than 26 hours.

## Cost and operations

- Everything here is open source. On-prem, the extra cost is one small VM for quorum and off-site backup storage.
- One person can run this: git is the source of truth, Argo CD shows what runs where, rollbacks are a revert.
- Not done yet, by choice (see README "What I would do next"): NetworkPolicies, monitoring stack, image signing,
  managed secrets (Sealed Secrets / External Secrets instead of creating Secrets by hand).
