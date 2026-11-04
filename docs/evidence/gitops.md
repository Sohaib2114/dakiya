# GitOps evidence (local k3d cluster, 4 Nov 2026)

Logs copied from the terminal. Cluster: k3d `dakiya`, Argo CD v3.5.6, ApplicationSet `dakiya` (one app per `deploy/envs/` folder).

## 1. First sync: three deployments, each with its own version and config

```
$ kubectl -n argocd get applications
NAME                    SYNC     HEALTH    REVISION
dakiya-partner-retail   Synced   Healthy   d4896cec236a527cbdc339f9b381a34f1b561cbc
dakiya-production       Synced   Healthy   d4896cec236a527cbdc339f9b381a34f1b561cbc
dakiya-staging          Synced   Healthy   d4896cec236a527cbdc339f9b381a34f1b561cbc

$ kubectl -n dakiya-staging get deploy -o wide (images)
NAME            READY   IMAGE
dakiya-api      1       ghcr.io/sohaib2114/dakiya-api:sha-489bd76
dakiya-worker   1       ghcr.io/sohaib2114/dakiya-worker:sha-489bd76

$ kubectl -n dakiya-production get deploy -o wide (images)
NAME            READY   IMAGE
dakiya-api      2       ghcr.io/sohaib2114/dakiya-api:sha-57b78fe
dakiya-worker   2       ghcr.io/sohaib2114/dakiya-worker:sha-57b78fe

$ kubectl -n dakiya-partner-retail get deploy -o wide (images)
NAME            READY   IMAGE
dakiya-api      2       ghcr.io/sohaib2114/dakiya-api:sha-57b78fe
dakiya-worker   1       ghcr.io/sohaib2114/dakiya-worker:sha-57b78fe

$ curl http://staging.dakiya.localhost:8081/readyz
{"status":"ready"}

$ python3 scripts/send_scans.py http://staging.dakiya.localhost:8081
sent 20 scans
{
  "tracking_id": "DKY-1000",
  "status": "delivered",
  ...

$ python3 scripts/send_scans.py http://prod.dakiya.localhost:8081
sent 20 scans
{
  "tracking_id": "DKY-1000",
  "status": "delivered",
  ...

$ kubectl -n dakiya-partner-retail get ingress
No resources found in dakiya-partner-retail namespace.

$ kubectl -n dakiya-partner-retail port-forward svc/dakiya-api 8082:80 &  python3 scripts/send_scans.py http://localhost:8082
sent 20 scans
{
  "tracking_id": "DKY-1000",
  "status": "delivered",
  ...
```

## 2. Argo CD undoing a manual kubectl change (selfHeal)

```
19:31:16 $ kubectl -n dakiya-production get deploy dakiya-api
NAME         READY   UP-TO-DATE   AVAILABLE   AGE
dakiya-api   2/2     2            2           112s

19:31:16 $ kubectl -n dakiya-production scale deploy dakiya-api --replicas=0   # manual change, not in git
deployment.apps/dakiya-api scaled
19:31:17 replicas wanted/ready: 0/   argo: OutOfSync/Healthy
19:31:19 replicas wanted/ready: 2/   argo: Synced/Progressing
19:31:21 replicas wanted/ready: 2/2   argo: Synced/Healthy

$ kubectl -n argocd get application dakiya-production -o jsonpath='{.status.operationState.message}'
{"automated":true}  successfully synced (all tasks run)
```

## 3. Promotion to production by pull request (#6)

Only `deploy/envs/production/values.yaml` changed (`sha-57b78fe` -> `sha-489bd76`). After the merge Argo CD rolled production one pod at a time:

```
19:33:54 PR #6 merged (production: sha-57b78fe -> sha-489bd76). Argo CD polls git; refresh asked to skip the 3 minute wait:
19:33:54 api image: sha-57b78fe  updated/ready/wanted: 2/2/2
19:33:57 api image: sha-57b78fe  updated/ready/wanted: 2/2/2
19:34:00 api image: sha-489bd76  updated/ready/wanted: 1/2/2
19:34:04 api image: sha-489bd76  updated/ready/wanted: 2/2/2

NAME                SYNC     HEALTH        REVISION
dakiya-production   Synced   Progressing   6d2caf3a75af2b0dcef4979204055e56a7f56dfc

```

The first request after the rollout returned **502**. Measured during a rolling restart: 5 of 276 requests failed. Fixed in PR #7 (`preStop: sleep 5`):

```
Rolling restart of production api while calling /healthz every 0.1s for 60s
before the fix (preStop missing): 271 ok, 5 failed
after the fix (preStop sleep 5): 487 ok, 0 failed
```

## 4. A new build reaching staging with nobody running a command

```
19:38:18 PR #7 merged to main. No command run after this; only watching.
19:38:18 staging api image: ghcr.io/sohaib2114/dakiya-api:sha-489bd76
19:40:40 CI on main: run 41849498439 6258755 completed success
19:40:43 CI commit: 8cf18e7 github-actions[bot]: staging: deploy sha-6258755
19:40:43 staging api image: sha-489bd76  updated/ready: 1/1
19:44:54 staging api image: sha-6258755  updated/ready: 1/1
NAME             SYNC     HEALTH        REVISION                                   BY
dakiya-staging   Synced   Progressing   8cf18e763fb8a69609b6a835260afd688606c9ce   true
```
About 6.5 minutes from merge to staging: ~2.5 min CI, the rest is Argo CD's 3-minute git poll.

## 5. A fix reaching every deployment (#8, #9)

Workers crash-looped while idle (redis-py 8 read timeout). Fixed in #8, CI put it on staging, one PR (#9) promoted it to production and partner. Final state, 90 s after the rollout with no scans:

```
$ kubectl -n argocd get applications
NAME                    SYNC     HEALTH
dakiya-partner-retail   Synced   Healthy
dakiya-production       Synced   Healthy
dakiya-staging          Synced   Healthy

$ kubectl -n dakiya-staging get pods
NAME                             READY   STATUS    RESTARTS   AGE
dakiya-api-756fbc869d-qbtp5      1/1     Running   0          13m
dakiya-postgres-0                1/1     Running   0          48m
dakiya-redis-0                   1/1     Running   0          48m
dakiya-worker-7d679f4fb7-m4zgw   1/1     Running   0          13m

$ kubectl -n dakiya-production get pods
NAME                             READY   STATUS    RESTARTS   AGE
dakiya-api-7fd7c6456f-djlns      1/1     Running   0          117s
dakiya-api-7fd7c6456f-x8ffz      1/1     Running   0          115s
dakiya-postgres-0                1/1     Running   0          48m
dakiya-redis-0                   1/1     Running   0          48m
dakiya-worker-7d679f4fb7-bvj8t   1/1     Running   0          117s
dakiya-worker-7d679f4fb7-x9mzt   1/1     Running   0          116s

$ kubectl -n dakiya-partner-retail get pods
NAME                             READY   STATUS    RESTARTS   AGE
dakiya-api-756fbc869d-9r288      1/1     Running   0          2m29s
dakiya-api-756fbc869d-pjt2n      1/1     Running   0          2m26s
dakiya-postgres-0                1/1     Running   0          48m
dakiya-redis-0                   1/1     Running   0          48m
dakiya-worker-7d679f4fb7-8rmqt   1/1     Running   0          2m29s

```
