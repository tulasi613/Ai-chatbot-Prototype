# AI-Powered Smart Restock Chatbot Prototype

## Overview
This repository contains the prototype for an AI-powered conversational chatbot and realtime dashboard designed for smart inventory management. The system provides predictive restock analysis, automated customer alerts, and intelligent product alternatives. 

## Key Features
* **Customer-Facing AI Chatbot:** A conversational interface allowing users to inquire about product availability.
* **Restock Predictions:** Machine learning/predictive logic to estimate when out-of-stock items will return.
* **Smart Subscriptions & Alerts:** Allows customers to subscribe to specific out-of-stock products and receive automated notifications when inventory is updated.
* **Product Alternatives:** A similarity engine that recommends ranked in-stock alternatives when a user's desired product is unavailable.
* **Admin Dashboard:** A real-time monitoring interface for inventory management and tracking subscription metrics.

## Repository Structure
* `/restock_ai_prototype` - Main project directory.
  * `/task2_chatbot` - Core chatbot application containing the NLP/NLU logic and API routes.
  * `/backend` - Backend services including the predictor engine and alert notifier.
  * `/chatbot_ui` - Frontend HTML/CSS/JS for the customer chatbot interface.
  * `/admin_dashboard` - Codebase for the administrator view.
  * `/database` - SQL schemas and seed data for inventory and user subscriptions.
* `/taskupdates` - Documentation regarding database schemas and recent project updates.

## Tech Stack
* **Backend:** Python (FastAPI/Flask), Machine Learning / NLU modules
* **Frontend:** HTML5, CSS, vanilla JavaScript
* **Database:** SQL (MySQL / SQLite)
