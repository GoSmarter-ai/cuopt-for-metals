using 'main.bicep'

// ── Edit these values before deploying ────────────────────────────────────────

// Short environment tag: 'dev', 'staging', or 'prod'
param environmentName = 'dev'

// Azure region – choose one close to your data
param location = 'australiaeast'

// Prefix used to name all resources (max ~12 chars, lowercase alphanumeric)
param projectName = 'cuoptmetals'

// Container image for the cuOpt solver.
// Build and push with: docker build -t <registry>/cuopt-solver:latest src/cuopt-solver
// then push to Azure Container Registry before deploying.
param solverImage = 'cuoptmetals.azurecr.io/cuopt-solver:latest'

// Default stock bar length in millimetres
param stockLengthMm = 6000
