# Multi-Cloud Anomaly Alerts

A Python tool that pulls metrics from AWS CloudWatch, Azure Monitor and GCP Cloud Monitoring and flags anomalies using simple statistical methods. Each anomaly is posted to Slack as a rich alert with the observed value, the baseline, and recommended next steps. It runs as a short-lived job on any scheduler and is configured with a single YAML file.

```mermaid
flowchart LR
    subgraph Providers
        A[AWS CloudWatch]
        B[Azure Monitor]
        C[GCP Monitoring]
    end
    A --> D[Normalize and detect]
    B --> D
    C --> D
    D --> E[Dedup and cooldown]
    E --> F[Recommended actions]
    F --> G[Slack alert]

    classDef step fill:#e8f0fe,stroke:#4a6fa5,stroke-width:1.5px,color:#111111
    classDef out fill:#fff4d6,stroke:#b58900,stroke-width:2px,color:#111111
    class A,B,C,D,E,F step
    class G out
    style Providers fill:#f6f8fa,stroke:#57606a,color:#111111
```
