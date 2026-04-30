{{/*
Expand the name of the chart.
*/}}
{{- define "public-backend.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified release name.
Truncated at 63 characters because some Kubernetes name fields have this limit.
*/}}
{{- define "public-backend.fullname" -}}
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
{{- define "public-backend.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to every resource.
*/}}
{{- define "public-backend.labels" -}}
helm.sh/chart: {{ include "public-backend.chart" . }}
{{ include "public-backend.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels (stable — used in matchLabels / Services).
*/}}
{{- define "public-backend.selectorLabels" -}}
app.kubernetes.io/name: {{ include "public-backend.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Public-backend image reference.
  ghcr.io/bcgov/transportation-forms/public-backend:<tag>
*/}}
{{- define "public-backend.image" -}}
{{- printf "%s/%s/public-backend:%s" .Values.global.registry .Values.global.repository .Values.image.tag }}
{{- end }}
