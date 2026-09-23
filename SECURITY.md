# Security reporting

This is a reference demo, not a production backup-control service. Real Entra
authentication and operator authorization remain required even in simulated mode.
Only reviewed, explicitly approved environments should connect to a live
Commvault service.

Report suspected vulnerabilities privately to the repository owner. If GitHub
private vulnerability reporting is enabled, use **Security > Report a
vulnerability**. Otherwise contact the owner through an approved private channel.
Do not post credentials, access tokens, Terraform state, tenant details, or client
server inventories in public issues.

Include the affected revision, prerequisites, a minimal reproduction using
synthetic data, and the expected versus actual behavior. Do not test destructive
operations against real backup systems without explicit authorization.

Maintainers should enable private reporting before public release, review
dependency advisories, and document remediation. No support SLA or production
security certification is implied.
