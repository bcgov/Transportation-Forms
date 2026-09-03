{{/*
Expand the name of the chart.
*/}}
{{- define "public-frontend.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified release name.
Truncated at 63 characters because some Kubernetes name fields have this limit.
*/}}
{{- define "public-frontend.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Chart label (name + version).
*/}}
{{- define "public-frontend.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to every resource.
*/}}
{{- define "public-frontend.labels" -}}
helm.sh/chart: {{ include "public-frontend.chart" . }}
{{ include "public-frontend.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels (stable — used in matchLabels / Services).
*/}}
{{- define "public-frontend.selectorLabels" -}}
app.kubernetes.io/name: {{ include "public-frontend.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
ServiceAccount name.
*/}}
{{- define "public-frontend.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "public-frontend.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Image reference. Honours .Values.image.repository if set, else falls back to
{registry}/{repository}/public-frontend.
*/}}
{{- define "public-frontend.image" -}}
{{- $repo := .Values.image.repository | default (printf "%s/%s/public-frontend" .Values.global.registry .Values.global.repository) -}}
{{- if .Values.image.digest }}
{{- printf "%s@%s" $repo .Values.image.digest }}
{{- else }}
{{- printf "%s:%s" $repo .Values.image.tag }}
{{- end }}
{{- end }}

{{/*
Internal-auth Secret name. Defaults to "{{ fullname }}-internal-auth".
*/}}
{{- define "public-frontend.internalAuthSecretName" -}}
{{- default (printf "%s-internal-auth" (include "public-frontend.fullname" .)) .Values.internalAuth.secretName }}
{{- end }}

{{/*
Backend (public-backend) Service DNS name within the namespace.
Pattern matches the public-backend chart fullname helper:
  {{ release }}-public-backend
*/}}
{{- define "public-frontend.backendHost" -}}
{{- printf "%s-public-backend" .Release.Name }}
{{- end }}
