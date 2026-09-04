{{/*
Expand the name of the chart.
*/}}
{{- define "backend.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified release name.
Truncated at 63 characters because some Kubernetes name fields have this limit.
*/}}
{{- define "backend.fullname" -}}
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
{{- define "backend.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to every resource.
*/}}
{{- define "backend.labels" -}}
helm.sh/chart: {{ include "backend.chart" . }}
{{ include "backend.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels (stable — used in matchLabels / Services).
*/}}
{{- define "backend.selectorLabels" -}}
app.kubernetes.io/name: {{ include "backend.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Backend image reference.
  ghcr.io/bcgov/transportation-forms/backend:<tag|@digest>
*/}}
{{- define "backend.image" -}}
{{- if .Values.image.digest }}
{{- printf "%s/%s/backend@%s" .Values.global.registry .Values.global.repository .Values.image.digest }}
{{- else }}
{{- printf "%s/%s/backend:%s" .Values.global.registry .Values.global.repository .Values.image.tag }}
{{- end }}
{{- end }}

{{/*
Migrations image reference.
  ghcr.io/bcgov/transportation-forms/migrations:<tag|@digest>
*/}}
{{- define "backend.migrationsImage" -}}
{{- if .Values.image.migrationsDigest }}
{{- printf "%s/%s/migrations@%s" .Values.global.registry .Values.global.repository .Values.image.migrationsDigest }}
{{- else }}
{{- printf "%s/%s/migrations:%s" .Values.global.registry .Values.global.repository .Values.image.migrationsTag }}
{{- end }}
{{- end }}
