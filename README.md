# store-intelligence

Project Title
Store Intelligence: Real-Time Retail Analytics Pipeline

Tagline
A containerised end-to-end computer vision and analytics pipeline that turns raw CCTV footage into actionable retail insights.

Project Description
🌟 The Problem
Physical retail spaces often lack the granular analytics available to e-commerce platforms. Store managers need to know not just how many people entered, but how they moved through the store, where they lingered, and why they abandoned queues.

💡 Our Solution
The Store Intelligence system solves this by analyzing raw CCTV footage using a robust object detection pipeline, extracting behavioural data, and powering a real-time analytics backend. The platform provides insights into:

The "North Star" Conversion Rate (calculated via entry vs. billing queue visitors)
Funnel Drop-offs (Entry ➔ Zone Exploration ➔ Billing Queue)
Anomaly Detection (Queue spikes, Dead zones, and Conversion rate drops)
Average Dwell Times per store zone
🏗 Architecture & Workflow
Our system is split into two primary decoupled components:

The Detection Pipeline (Offline/Edge): Uses YOLOv8 nano and ByteTrack to process video frames. It handles staff exclusion and zone mapping, then converts this raw tracking data into structured JSON events. These events are grouped into batches and emitted to the backend.
The Analytics API (Backend): A high-performance FastAPI service backed by an asynchronous PostgreSQL database. It exposes idempotent ingestion endpoints (ON CONFLICT DO NOTHING) and runs complex SQL aggregations on the fly to calculate metrics without needing a heavy OLAP database. Both components are containerised using Docker Compose.
🛠 Tech Stack
Computer Vision: Python, OpenCV, YOLOv8 (Ultralytics), ByteTrack
Backend API: Python, FastAPI, Pydantic, Uvicorn
Database: PostgreSQL 15, SQLAlchemy 2.0 (Asyncpg)
Orchestration: Docker, Docker Compose
🚀 Key Design Decisions
YOLOv8 Nano: Chosen for its real-time processing capabilities on CPU, allowing the pipeline to run efficiently without requiring expensive GPU infrastructure.
PostgreSQL over NoSQL: We opted for a relational database with strict constraints to ensure absolute data integrity for analytical queries, enforcing idempotency at the database level.
Decoupled Architecture: By separating the heavy computer vision processing script from the lightweight API, we ensured the web server remains highly available and doesn't crash during intensive video processing.
