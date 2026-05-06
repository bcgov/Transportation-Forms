#!/bin/sh
# Helm post-renderer: patches openshift: true → openshift: false for k3s
sed 's/openshift: true/openshift: false/g'
