# Shipped examples

sagaz comes with complete business scenarios, grouped by industry. They are installed with
the package, so you can run any of them right after `pip install sagaz`:

```bash
sagaz examples list                 # every example, by industry
sagaz examples run wire_transfer    # run one, by the name in the list
sagaz examples select               # browse and run interactively
```

Each one is a single file that defines a saga, runs it and logs what happens. **Pivot**
marks the examples with a point of no return, and **Recovery** those with a
`@forward_recovery` handler. The name links to the source.

## Banking & Financial Services

| Example | What it is | Pivot | Recovery |
|---|---|:-:|:-:|
| [`crypto_exchange`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/banking_finance/finance/crypto_exchange/main.py) | Cryptocurrency Exchange | ✓ | ✓ |
| [`insurance_claim`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/banking_finance/insurance/insurance_claim/main.py) | Insurance Claim Processing | ✓ |  |
| [`loan_origination`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/banking_finance/finance/loan_origination/main.py) | Loan Origination | ✓ |  |
| [`payment_processing`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/banking_finance/finance/payment_processing/main.py) | Payment Processing |  |  |
| [`property_closing`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/banking_finance/real_estate/property_closing/main.py) | Property Closing | ✓ | ✓ |
| [`rental_application`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/banking_finance/real_estate/rental_application/main.py) | Rental Application Processing | ✓ | ✓ |
| [`trade_execution`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/banking_finance/finance/trade_execution/main.py) | Trade Execution |  |  |
| [`wire_transfer`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/banking_finance/finance/wire_transfer/main.py) | Cross-Border Wire Transfer | ✓ |  |

## Retail & eCommerce

| Example | What it is | Pivot | Recovery |
|---|---|:-:|:-:|
| [`order_processing`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/retail_ecommerce/commerce/order_processing/main.py) | E-commerce Order Processing |  |  |

## Manufacturing & Automotive

| Example | What it is | Pivot | Recovery |
|---|---|:-:|:-:|
| [`chemical_reactor`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/manufacturing_automotive/manufacturing/chemical_reactor/main.py) | Chemical Reactor | ✓ | ✓ |
| [`production`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/manufacturing_automotive/manufacturing/production/main.py) | Manufacturing Production | ✓ | ✓ |
| [`three_d_printing`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/manufacturing_automotive/manufacturing/three_d_printing/main.py) | 3D Printing Job | ✓ |  |

## Healthcare & Life Sciences

| Example | What it is | Pivot | Recovery |
|---|---|:-:|:-:|
| [`lab_processing`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/healthcare_life_sciences/healthcare/lab_processing/main.py) | Lab Test Processing | ✓ | ✓ |
| [`patient_onboarding`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/healthcare_life_sciences/healthcare/patient_onboarding/main.py) | Healthcare Patient Onboarding |  |  |
| [`prescription`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/healthcare_life_sciences/healthcare/prescription/main.py) | Prescription Fulfillment | ✓ |  |
| [`procedure_scheduling`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/healthcare_life_sciences/healthcare/procedure_scheduling/main.py) | Medical Procedure Scheduling | ✓ | ✓ |

## Public Sector & Education

| Example | What it is | Pivot | Recovery |
|---|---|:-:|:-:|
| [`course_enrollment`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/public_sector_education/education/course_enrollment/main.py) | Course Enrollment | ✓ |  |
| [`exam_proctoring`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/public_sector_education/education/exam_proctoring/main.py) | Exam Proctoring | ✓ | ✓ |
| [`power_grid`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/public_sector_education/energy/power_grid/main.py) | Power Grid Switching | ✓ | ✓ |
| [`regulatory_filing`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/public_sector_education/government/regulatory_filing/main.py) | Regulatory Filing | ✓ |  |
| [`smart_meter`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/public_sector_education/energy/smart_meter/main.py) | Smart Meter Deployment | ✓ |  |
| [`visa_application`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/public_sector_education/government/visa_application/main.py) | Visa Application Processing | ✓ |  |

## Communications, Media & Entertainment

| Example | What it is | Pivot | Recovery |
|---|---|:-:|:-:|
| [`content_publishing`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/communications_media_entertainment/media/content_publishing/main.py) | Content Publishing Pipeline | ✓ |  |
| [`in_game_purchase`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/communications_media_entertainment/gaming/in_game_purchase/main.py) | In-Game Purchase | ✓ |  |
| [`live_streaming`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/communications_media_entertainment/media/live_streaming/main.py) | Live Streaming | ✓ | ✓ |
| [`number_porting`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/communications_media_entertainment/telecom/number_porting/main.py) | Mobile Number Porting | ✓ | ✓ |
| [`sim_provisioning`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/communications_media_entertainment/telecom/sim_provisioning/main.py) | SIM Provisioning | ✓ | ✓ |
| [`tournament_match`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/communications_media_entertainment/gaming/tournament_match/main.py) | Tournament Match | ✓ |  |

## Consumer Goods

| Example | What it is | Pivot | Recovery |
|---|---|:-:|:-:|
| [`co_packer_order`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/consumer_goods/supply/co_packer_order/main.py) | Co-Packer Order Saga Example (Consumer Goods) | ✓ |  |
| [`packaging_switch`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/consumer_goods/supply/packaging_switch/main.py) | Packaging Switch Saga Example (Consumer Goods) | ✓ |  |
| [`product_launch`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/consumer_goods/product/product_launch/main.py) | Product Launch Saga Example (Consumer Goods) | ✓ |  |
| [`product_recall`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/consumer_goods/product/product_recall/main.py) | Product Recall Saga Example (Consumer Goods) | ✓ |  |
| [`retail_replenishment`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/consumer_goods/distribution/retail_replenishment/main.py) | Retail Replenishment Saga Example (Consumer Goods) | ✓ |  |
| [`returns_processing`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/consumer_goods/direct_to_consumer/returns_processing/main.py) | Returns Processing Saga Example (Consumer Goods) | ✓ |  |
| [`subscription_box`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/consumer_goods/direct_to_consumer/subscription_box/main.py) | Subscription Box Saga Example (Consumer Goods) | ✓ |  |
| [`trade_promotion`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/consumer_goods/distribution/trade_promotion/main.py) | Trade Promotion Saga Example (Consumer Goods) | ✓ |  |

## Software & Technology

| Example | What it is | Pivot | Recovery |
|---|---|:-:|:-:|
| [`ai_content_pipeline`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/ai/ai_content_pipeline/main.py) | AI Content Generation Pipeline Saga |  |  |
| [`data_migration`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/data/data_migration/main.py) | Data Migration |  |  |
| [`data_quality_gate`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/data/data_quality_gate/main.py) | Data Quality Gate |  |  |
| [`device_orchestration`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/iot/device_orchestration/main.py) | IoT Device Orchestration |  |  |
| [`django_app`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/integrations/django_app/demo.py) | Django Integration Demo |  |  |
| [`etl_pipeline`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/data/etl_pipeline/main.py) | ETL Pipeline |  |  |
| [`fastapi_app`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/integrations/fastapi_app/demo.py) | FastAPI Integration Demo |  |  |
| [`federated_learning`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/ai/federated_learning/main.py) | Edge Computing Federated Learning |  |  |
| [`flask_app`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/integrations/flask_app/demo.py) | Flask Integration Demo |  |  |
| [`lakehouse_ingestion`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/data/lakehouse_ingestion/main.py) | Lakehouse Ingestion |  |  |
| [`langgraph_support_agent`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/ai/langgraph_support_agent/main.py) | LangGraph Customer Support Agent Saga |  |  |
| [`mermaid_visualization`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/observability/mermaid_visualization/main.py) | Mermaid Visualization Demo for Sagaz |  |  |
| [`metrics_monitoring`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/observability/metrics_monitoring/main.py) | Monitoring demo for saga orchestration |  |  |
| [`order_recovery`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/observability/order_recovery/main.py) | Order Processing Recovery - Replay failed saga from checkpoint |  |  |
| [`pydantic_ai_research`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/ai/pydantic_ai_research/main.py) | Pydantic AI Research Assistant Saga |  |  |
| [`simple_demo`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/observability/simple_demo/main.py) | Simple Replay Demo - Minimal |  |  |
| [`smart_grid`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/iot/smart_grid/main.py) | Smart Grid Energy Management |  |  |
| [`time_travel`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/observability/time_travel/main.py) | Time-Travel Demo - Query historical saga state for auditing |  |  |
| [`training`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/software_technology/ai/training/main.py) | ML Training Pipeline |  |  |

## Travel & Hospitality

| Example | What it is | Pivot | Recovery |
|---|---|:-:|:-:|
| [`drone_delivery`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/travel_hospitality/logistics/drone_delivery/main.py) | Supply Chain Drone Delivery |  |  |
| [`travel_booking`](https://github.com/brunolnetto/sagaz/blob/main/sagaz/examples/travel_hospitality/travel/travel_booking/main.py) | Travel Booking |  |  |
