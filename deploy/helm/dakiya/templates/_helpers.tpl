{{/* Image name for a service: <registry>/dakiya-<name>:<tag>. Fails if no tag is set. */}}
{{- define "dakiya.image" -}}
{{ .root.Values.image.registry }}/dakiya-{{ .name }}:{{ required "image.tag is required (set it in deploy/envs/<env>/values.yaml)" .root.Values.image.tag }}
{{- end }}

{{/* Security settings shared by api and worker: no root, no extra Linux rights, read-only disk. */}}
{{- define "dakiya.containerSecurity" -}}
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: ["ALL"]
{{- end }}
