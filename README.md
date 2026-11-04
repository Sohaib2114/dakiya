# Dakiya Tracking

Parcel tracking service. Depots and riders send scan events, customers check where their parcel is.

```
POST /scans ──> api ──> Redis queue "scans" ──> worker ──> PostgreSQL <── api <── GET /parcels/{id}
```

| Path | What |
|---|---|
| `api/`, `worker/` | service code and Dockerfiles |
| `docker-compose.yml`, `.env.example` | run everything locally / on a server with Docker |
| `.github/workflows/ci.yml` | CI: test, secret scan, chart check, end-to-end test, build, image scan, push to GHCR, update staging |
| `deploy/helm/dakiya/` | Helm chart (api, worker, PostgreSQL, Redis, ingress) |
| `deploy/envs/<name>/values.yaml` | one folder per deployment: `staging`, `production`, `partner-retail` |
| `deploy/argocd/` | Argo CD project + ApplicationSet (one Application per folder) |
| `deploy/k3d/cluster.yaml` | local Kubernetes cluster for testing |
| `DESIGN.md` | high availability, ten-client model, alerts |

## How to run it

Needs: Linux or macOS with **Docker and Docker Compose v2** (`docker compose version`), `git`, `curl`, `openssl`, `python3`.

### 1. Docker Compose

```bash
git clone https://github.com/Sohaib2114/dakiya.git && cd dakiya
cp .env.example .env
sed -i "s/^DB_PASSWORD=.*/DB_PASSWORD=$(openssl rand -hex 16)/" .env    # macOS: sed -i ''
docker compose up -d --build --wait          # builds, starts, waits until db, redis and api are healthy
python3 scripts/send_scans.py http://localhost:8080     # sends 20 scans, prints one parcel ("delivered")
```

API: <http://localhost:8080> (this machine only), `/healthz` (alive), `/readyz` (can reach PostgreSQL and Redis).
Data survives `docker compose down && docker compose up -d` (named volumes). `docker compose down -v` deletes it.

### 2. Local Kubernetes + GitOps

Tools go into one folder, nothing system-wide (`rm -rf ~/dakiya-tools` removes them). kubectl is assumed installed
(any recent version); otherwise get it from <https://kubernetes.io/docs/tasks/tools/>.

```bash
mkdir -p ~/dakiya-tools/bin && cd ~/dakiya-tools/bin
curl -fsSL -o k3d https://github.com/k3d-io/k3d/releases/download/v5.8.3/k3d-linux-amd64 && chmod +x k3d
curl -fsSL https://get.helm.sh/helm-v3.22.1-linux-amd64.tar.gz | tar -xz --strip-components=1 linux-amd64/helm
export PATH=~/dakiya-tools/bin:$PATH KUBECONFIG=~/dakiya-tools/kubeconfig
cd -   # back to the repo
```

Cluster and Argo CD:

```bash
k3d cluster create --config deploy/k3d/cluster.yaml --kubeconfig-update-default=false --wait
k3d kubeconfig get dakiya > ~/dakiya-tools/kubeconfig

kubectl create namespace argocd
kubectl apply -n argocd --server-side -f https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.6/manifests/install.yaml
kubectl -n argocd wait --for=condition=available deploy --all --timeout=600s
```

Secrets (never in git). The repo is private, so Argo CD needs a token that can read it
(GitHub fine-grained token, *Contents: read-only* on this repo):

```bash
for env in staging production partner-retail; do
  kubectl create namespace dakiya-$env
  kubectl -n dakiya-$env create secret generic dakiya-db --from-literal=password="$(openssl rand -hex 16)"
done

read -s -p "GitHub token: " TOKEN; echo
kubectl -n argocd create secret generic dakiya-repo --from-literal=type=git \
  --from-literal=url=https://github.com/Sohaib2114/dakiya.git \
  --from-literal=username=<your-github-user> --from-literal=password="$TOKEN"
kubectl -n argocd label secret dakiya-repo argocd.argoproj.io/secret-type=repository
unset TOKEN
```

If the images on GHCR are private, also create a pull secret in each namespace (token with `read:packages` only):
`kubectl -n dakiya-$env create secret docker-registry ghcr-pull --docker-server=ghcr.io --docker-username=<user> --docker-password=<token>`

Hand the deployments to Argo CD:

```bash
kubectl apply -f deploy/argocd/project.yaml -f deploy/argocd/applicationset.yaml
kubectl -n argocd get applications     # repeat until all three are Synced / Healthy (2-5 minutes)
```

Check it works:

```bash
curl http://staging.dakiya.localhost:8081/readyz
python3 scripts/send_scans.py http://staging.dakiya.localhost:8081
python3 scripts/send_scans.py http://prod.dakiya.localhost:8081
# partner copy has no ingress (no inbound access); reach it through the Kubernetes API:
kubectl -n dakiya-partner-retail port-forward svc/dakiya-api 8082:80 &
python3 scripts/send_scans.py http://localhost:8082
```

If `*.localhost` does not resolve on your machine, add the names to `/etc/hosts` as `127.0.0.1`, or use
`curl -H 'Host: staging.dakiya.localhost' http://127.0.0.1:8081/readyz`.

Argo CD UI: `kubectl -n argocd port-forward svc/argocd-server 8443:443`, open <https://localhost:8443>, user `admin`,
password from `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d`.

Remove everything: `k3d cluster delete dakiya`, `docker compose down -v`, `rm -rf ~/dakiya-tools`.

### 3. Releases

1. Merge a pull request to `main`. CI tests, builds and scans the images, pushes `ghcr.io/sohaib2114/dakiya-{api,worker}:sha-<commit>`
   and commits the new tag to `deploy/envs/staging/values.yaml`. Argo CD deploys staging. Nobody runs a command.
2. Promote: open a pull request that copies the tag from `deploy/envs/staging/values.yaml` into
   `deploy/envs/production/values.yaml` (or the partner's folder). After review and merge, Argo CD deploys it.
3. Roll back: revert that pull request.

## Findings

Ordered by what I fixed first: secrets, then data loss, then things that take the service down, then the rest.

| # | Problem | Risk | Status |
|---|---|---|---|
| 1 | `.env` with the production DB password and registry push credentials committed in the first commit | anyone with the repo has production credentials | **Fixed**: untracked, `.env.example` added. History kept (brief), so the credentials stay readable in old commits: treated as leaked, rotated locally; the **real production DB password and the `dakiya-ci` registry account must be rotated by the owner** (I have no access) |
| 2 | Same DB password hardcoded in `docker-compose.yml`, `api/app/config.py`, `worker/worker.py` (as defaults) and Helm `values.yaml` | leak; every environment shares one password | **Fixed**: password only from `.env` / Kubernetes Secret; app stops with a clear error if it is missing |
| 3 | `api/Dockerfile` baked `DB_PASSWORD` into the image (`ARG`/`ENV`), CI passed it as a build-arg | anyone who can pull the image reads the password | **Fixed**: no secrets at build time; `.dockerignore` keeps `.env` out of the build |
| 4 | Old CI: `set -x` with `docker login -p` | registry password in the job log | **Fixed**: removed; new CI uses `GITHUB_TOKEN` |
| 5 | Old CI deployed to production over SSH on every push to any branch; SSH key left on disk; `StrictHostKeyChecking=no` | untested code goes live; key reuse; man-in-the-middle | **Fixed**: no deploy step; Argo CD pulls from git |
| 6 | Old CI ignored test failures (`pytest \|\| true`) | broken code ships | **Fixed** |
| 7 | Repo-local git config set to the previous engineer's name and email | my commits were attributed to him | **Fixed** before pushing my commits |
| 8 | No secret scanning; gitleaks default rules did **not** detect these passwords | it happens again | **Fixed**: gitleaks in CI over full history with custom rules for hand-written passwords; old rotated leaks listed in `.gitleaksignore` |
| 9 | PostgreSQL without a volume (Compose) and on `emptyDir` (Helm) | all parcels lost on every restart (tested: 200 → 404 after `down`/`up`) | **Fixed**: named volume / StatefulSet + PVC |
| 10 | Redis (the queue) without persistence | scans accepted (202) but not yet processed are lost on a Redis restart | **Fixed**: append-only file on a volume / PVC (tested: 20 queued scans survive) |
| 11 | Worker crashed at start (DB not ready) and never restarted; `depends_on` without health checks | service down after every reboot | **Fixed**: health checks, `service_healthy`, `restart: unless-stopped` |
| 12 | PostgreSQL 5432 and Redis 6379 published on all interfaces; Redis has no password; API on `0.0.0.0` | anyone on the network reads/writes the database and queue | **Fixed**: db/redis not published, API on `127.0.0.1`. Redis password **left** (only reachable inside the private network now; listed under next steps) |
| 13 | `:latest` images everywhere (`python:latest` already pulled Python 3.15; `postgres:latest` is 18 with a new data path) | builds change silently; a database major upgrade on restart | **Fixed**: base images pinned by digest, Postgres 17, Redis 7; Dependabot proposes updates as PRs and skips database majors |
| 14 | Images ran as root, 1.3 GB, with gcc/vim/curl, `uvicorn --reload` in production | bigger attack surface, dev file watcher in prod | **Fixed**: multi-stage, `python:3.12-slim`, user 10001, 240/200 MB, read-only root filesystem in Kubernetes. Trivy: 0 fixable HIGH/CRITICAL |
| 15 | Unpinned Python dependencies; pytest/httpx in production requirements | different code on each build | **Fixed**: pinned with `==`, dev tools in `requirements-dev.txt` |
| 16 | API logged to a file (`logs/api.log`) at DEBUG | logs lost with the container, invisible to `docker logs`/Kubernetes | **Fixed**: stdout, INFO |
| 17 | No health endpoint | nothing for Compose/Kubernetes to check | **Fixed**: `/healthz`, `/readyz` |
| 18 | Helm: Service selected `dakia-api` (typo), pods labelled `app: api` (Deployment rejected), API image hardcoded `dakiya/api:latest`, DB password in a ConfigMap, no probes/resources/security settings | chart could not install or serve traffic | **Fixed**: chart rewritten, tested on k3d |
| 19 | No staging, no record of which version runs where | untested releases, no rollback | **Fixed**: staging/production/partner folders, every image tagged with its commit, promotion by PR |
| 20 | API accepts any `status` value (`"teleported"`); test `test_rejects_unknown_status` fails (hidden by `\|\| true`) | bad data in the database | **Left** (app behaviour, not ops): CI went red on it; the test is marked `xfail(strict=True)` so CI is green, the bug stays visible, and the marker must be removed once the developers fix it |
| 21 | Worker removes a scan from Redis (`BRPOP`) before writing it to PostgreSQL | a worker crash between the two loses that scan | **Left** (app code): fix is `BLMOVE` to a processing list |
| 22 | API does not retry the database at start | in Kubernetes the API restarts until PostgreSQL is ready (2 restarts seen) | **Left**: harmless, Kubernetes handles it; an app-side retry would be cleaner |
| 23 | Old README: `docker-compose up`, API on port 8000 (Compose actually published 8080) | wrong instructions | **Fixed** (this README) |
| 24 | My laptop had Compose v1 (Python), broken by a newer `requests` library | could not build | Installed Compose v2; README states Compose v2 |
| 25 | Worker crash-looped in Kubernetes when no scans arrived: redis-py 8 times out the worker's waiting `BRPOP` after ~60 s (7.x waits forever). Hidden in Compose by `restart: unless-stopped`; the original unpinned requirements would have pulled it in on any rebuild | while the worker is in back-off (up to 5 min) scans wait and parcel status is stale | **Fixed**: `redis==7.4.1`, Dependabot skips redis-py majors, e2e job fails if the worker restarts during 70 s idle (PR #8). Proper app fix (`BRPOP` with a timeout in a loop) left to the developers |
| 26 | Rolling update dropped requests: a stopping pod leaves the Service and gets SIGTERM at the same time, the ingress still routes to it for a moment | failed requests on every release (measured 5 of 276) | **Fixed**: `preStop: sleep 5` (PR #7); measured again: 0 of 487 |

## Evidence

- Green pipeline on a pull request: <https://github.com/Sohaib2114/dakiya/actions/runs/41810734324>
- Green pipeline on `main` (images pushed, staging updated by CI): <https://github.com/Sohaib2114/dakiya/actions/runs/41840234768>
- CI's hand-off commit: `staging: deploy sha-489bd76` by `github-actions[bot]`
- Pipeline blocking a bad upgrade: Dependabot PR #3 (Postgres 17 → 18) failed the end-to-end job and was closed
- Promotion pull request to production: <https://github.com/Sohaib2114/dakiya/pull/6> (`sha-57b78fe` → `sha-489bd76`)
- A fix promoted to every deployment in one pull request: <https://github.com/Sohaib2114/dakiya/pull/9> (production + partner)
- GitOps sync and the service working: [`docs/evidence/gitops.md`](docs/evidence/gitops.md)

## Tools and why

| Tool | Why |
|---|---|
| Docker Compose v2 | how the service runs today; v1 is unmaintained |
| GitHub Actions + GHCR | brief; `GITHUB_TOKEN` means no stored registry password |
| gitleaks | secret scan over the whole history; small, fast, configurable rules |
| Trivy | image scan for known vulnerabilities |
| Dependabot | everything is pinned; it opens PRs when updates exist, and each PR runs the full pipeline |
| k3d | Kubernetes inside Docker: one binary, no system install, removed with one command; k3s brings ingress and storage |
| Helm | the starter already had a chart |
| Argo CD | pull-based GitOps with a UI that shows what runs where; ApplicationSet gives one app per folder |

## AI usage

I used **Claude Code** (Anthropic) as an assistant during the whole task: to scan the repository for secrets, to write
and fix code and config (gitleaks rules, Dockerfiles, the `/healthz` and `/readyz` endpoints, the pipeline, the Helm
chart, the Argo CD files) and to explain errors (Compose v1 crash, worker start order, permission errors after going
non-root, Postgres 18 data path). I decided what to fix and in which order, ran the checks and reviewed each change
before it was merged.

Where an AI or tool answer was wrong and how I caught it:
- **gitleaks said "no leaks found"** on a history that contains two passwords. I knew they were there, so I did not
  trust the result; the default rules only look for random-looking tokens. Custom rules were added and tested against
  the history until they found exactly the six known leaks.
- **The AI-written gitleaks rule then flagged the pipeline**: the line that generates a throwaway password
  (`DB_PASSWORD=$(openssl rand -hex 16)`) turned the first CI run red. The rule was fixed (a value built by a shell
  command is not a secret) and checked again against the six real leaks.
- **The first explanation of the worker crash was wrong.** Claude said redis-py 8's 5-second socket timeout would kill
  the worker after 5 s idle. A 15 s test showed no crash, so I measured instead of trusting it: the Kubernetes logs and a
  75 s Compose test showed the crash comes after ~60 s idle (1 restart on 8.1.0, 0 on 7.4.1). The CI check waits 70 s
  because of that measurement.
- **A first "data survives restart" test looked like a failure** (404 after restart) because scans were sent before
  the API had started. Checking the database directly showed the volume worked; the test was wrong, not the fix.

## Time spent

| Task | Hours |
|---|---|
| Reading the brief, setting up the repo | 0.5 |
| Secrets: finding, removing, scanning | 1.5 |
| Compose, images, health checks (task 1) | 2 |
| Pipeline (task 2) | 1 |
| Helm chart and local cluster (task 3) | 1 |
| GitOps, promotion, self-heal (task 4) | 1 |
| DESIGN.md and README (tasks 5, 6) | 1 |
| **Total** | **about 8** |

## What I would do next

- Branch protection on `main` (PR + green CI required) and `CODEOWNERS` for `deploy/envs/production/` and partner folders
- Secrets managed in git safely (Sealed Secrets or External Secrets) instead of `kubectl create secret` by hand
- Redis password; NetworkPolicies so only api/worker reach PostgreSQL and Redis
- Monitoring (Prometheus, the five alerts in `DESIGN.md`) and database backups with a restore test
- Publish the chart as a versioned OCI artifact so each client folder can pin a chart version
- Sign images (cosign) and generate SBOMs in CI
- App fixes for the development team: validate `status`, reliable queue (`BLMOVE`), retry the database at start
