{{/*
Expand the name of the chart.
*/}}
{{- define "app.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified release name.
Truncated at 63 characters because some Kubernetes name fields have this limit.
*/}}
{{- define "app.fullname" -}}
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
{{- define "app.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to every resource.
*/}}
{{- define "app.labels" -}}
helm.sh/chart: {{ include "app.chart" . }}
{{ include "app.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels (stable — used in matchLabels / Services).
*/}}
{{- define "app.selectorLabels" -}}
app.kubernetes.io/name: {{ include "app.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Backend image reference.
  ghcr.io/bcgov/transportation-forms/backend:<tag>
*/}}
{{- define "app.backend.image" -}}
{{- printf "%s/%s/backend:%s" .Values.global.registry .Values.global.repository .Values.global.tag }}
{{- end }}

{{/*
Frontend image reference.
  ghcr.io/bcgov/transportation-forms/frontend:<tag>
*/}}
{{- define "app.frontend.image" -}}
{{- printf "%s/%s/frontend:%s" .Values.global.registry .Values.global.repository .Values.global.tag }}
{{- end }}

{{/*
Migrations image reference.
  ghcr.io/bcgov/transportation-forms/migrations:<tag>
*/}}
{{- define "app.migrations.image" -}}
{{- printf "%s/%s/migrations:%s" .Values.global.registry .Values.global.repository .Values.global.tag }}
{{- end }}
