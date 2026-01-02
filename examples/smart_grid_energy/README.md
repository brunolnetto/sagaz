# Smart Grid Energy Management Saga

Demand response event orchestration for grid stabilization with real-time grid balancing, distributed energy resource coordination, and automatic incentive payments.

## Overview

This example demonstrates a complete demand response (DR) event workflow for smart grid management, coordinating with commercial buildings, industrial facilities, and battery storage systems to reduce energy demand during peak periods.

## Use Case

During extreme heat events or grid stress:
1. Forecast energy demand and identify potential grid overload
2. Select participating buildings and energy resources
3. Send demand reduction requests via OpenADR protocol
4. Monitor real-time consumption during event
5. Verify reduction targets were met
6. Calculate and distribute incentive payments
7. Settle financial transactions with grid operator

## Workflow

```
Grid Stress Detected
    ↓
[1] Forecast Energy Demand → (Compensation: Log cancellation)
    ↓
[2] Identify Participants (Buildings + DERs) → (Compensation: Notify cancellation)
    ↓
[3] Send Reduction Requests (OpenADR) → (Compensation: Send cancellation)
    ↓
[4] Monitor Real-Time Consumption → (Compensation: Stop monitoring)
    ↓
[5] Verify Reduction Targets Met → (Compensation: Log verification failure)
    ↓
[6] Calculate Incentive Payments → (Compensation: Void calculations)
    ↓
[7] Settle with Grid Operator (idempotent)
    ↓
Event Complete
```

## Key Features

### Real-Time Grid Balancing
- **ML-Based Demand Forecasting**: LSTM neural networks predict load
- **Dynamic Participant Selection**: Based on reduction potential and location
- **15-Second Monitoring**: Real-time consumption tracking via smart meters
- **Automatic Load Shedding**: Coordinated reduction across zones

### Distributed Energy Resources (DERs)
- **Commercial Buildings**: HVAC pre-cooling, lighting reduction
- **Industrial Facilities**: Production scheduling shifts
- **Battery Storage (BESS)**: Grid discharge during peak
- **Solar + Storage**: Grid support services

### OpenADR 2.0b Protocol
- Industry-standard demand response communication
- Event signals (moderate, high, critical)
- Participant opt-in/opt-out support
- Real-time acknowledgments

### Incentive Management
- Per-kWh reduction payments
- Performance-based compensation
- Compliance verification
- Automated settlement

## Files

- **main.py** - Complete saga implementation with demo scenarios

## Usage

```python
from examples.smart_grid_energy.main import SmartGridEnergySaga

# Create demand response event
saga = SmartGridEnergySaga(
    event_id="DR-2026-HEATWAVE-001",
    grid_operator_id="GRID-CAISO",
    target_reduction_mw=1.5,
    event_duration_hours=4,
    incentive_rate_per_kwh=0.15,
    simulate_failure=False
)

# Execute demand response
result = await saga.run({"event_id": saga.event_id})
```

## Running the Example

```bash
python examples/smart_grid_energy/main.py
```

Expected output shows:
1. **Scenario 1**: Successful demand response with payments
2. **Scenario 2**: Communication failure with cancellation

## Actions

### forecast_demand(ctx)
ML-based energy demand forecasting for event period.

**Returns:**
```python
{
    "event_id": "DR-2026-HEATWAVE-001",
    "forecast_method": "LSTM Neural Network",
    "baseline_demand_mw": 1250.5,
    "predicted_peak_mw": 1425.0,
    "confidence_level": 0.92,
    "weather_factors": {
        "temperature_f": 98,
        "humidity_percent": 75,
        "heat_index": "extreme"
    },
    "time_period": "4 hours"
}
```

### identify_participants(ctx)
Selects participating buildings and DERs based on reduction potential.

**Returns:**
```python
{
    "commercial_buildings": [
        {
            "building_id": "BLDG-1",
            "type": "office",
            "baseline_kw": 160,
            "reduction_potential_kw": 32,
            "location": "Zone-1"
        },
        # ... 19 more buildings
    ],
    "industrial_facilities": [...],  # 5 facilities
    "battery_storage": [...],        # 3 BESS units
    "total_participants": 28,
    "total_reduction_potential_mw": 2.15
}
```

### send_reduction_requests(ctx)
Sends DR requests via OpenADR 2.0b protocol.

**Returns:**
```python
{
    "event_id": "DR-2026-HEATWAVE-001",
    "protocol": "OpenADR 2.0b",
    "requests_sent": 28,
    "acknowledgments_received": 26,
    "opt_outs": 2,
    "target_reduction_mw": 1.5,
    "event_start": "2026-01-01T15:00:00Z",
    "event_end": "2026-01-01T19:00:00Z"
}
```

### monitor_consumption(ctx)
Real-time consumption monitoring via smart meters.

**Returns:**
```python
{
    "event_id": "DR-2026-HEATWAVE-001",
    "monitoring_interval_sec": 15,
    "total_samples": 960,  # 4 hours × 240 samples/hour
    "actual_reduction_mw": 1.31,
    "baseline_consumption_mw": 1250.5,
    "event_consumption_mw": 1141.3,
    "participant_compliance": {
        "full_compliance": 20,
        "partial_compliance": 6,
        "non_compliance": 2
    }
}
```

### verify_targets(ctx)
Verifies reduction targets were achieved.

**Returns:**
```python
{
    "event_id": "DR-2026-HEATWAVE-001",
    "target_reduction_mw": 1.5,
    "actual_reduction_mw": 1.31,
    "target_met": True,  # 87% ≥ 85% threshold
    "achievement_percent": 87.3,
    "grid_stability_maintained": True
}
```

### calculate_incentives(ctx)
Calculates performance-based incentive payments.

**Returns:**
```python
{
    "event_id": "DR-2026-HEATWAVE-001",
    "total_kwh_reduced": 5220,
    "incentive_rate_per_kwh": 0.15,
    "total_payment_usd": 783.00,
    "participant_payments": [
        {
            "participant_id": "PART-1",
            "reduction_kwh": 190.5,
            "payment_usd": 28.58
        },
        # ... 25 more participants
    ]
}
```

### settle_with_grid_operator(ctx)
Financial settlement with grid operator (idempotent).

**Returns:**
```python
{
    "event_id": "DR-2026-HEATWAVE-001",
    "grid_operator_id": "GRID-CAISO",
    "settlement_amount_usd": 783.00,
    "settlement_timestamp": "2026-01-01T19:00:00Z",
    "payment_method": "ACH Transfer",
    "confirmation_id": "SETTLE-DR-2026-HEATWAVE-001"
}
```

## Compensations

### log_forecast_cancellation(ctx)
Logs forecast cancellation for audit trail.

### notify_participants_cancellation(ctx)
Notifies all participants that event is canceled.

### send_cancellation_requests(ctx)
Sends OpenADR cancellation signals to all participants.

### stop_monitoring(ctx)
Stops real-time monitoring and saves collected data.

### log_verification_failure(ctx)
Logs verification rollback for audit.

### void_incentive_calculations(ctx)
Voids all payment calculations (no payments issued).

## Error Scenarios

### Communication Failure
If OpenADR system fails:
- All participants notified of cancellation
- Monitoring stopped
- No incentive payments issued
- Grid operator informed

### Target Not Met
If reduction target not achieved (< 85%):
- Partial payments based on actual reduction
- Event marked as partially successful
- Root cause analysis initiated

### Participant Non-Compliance
If participants don't reduce load:
- Reduced/no incentive payment to non-compliant participants
- Future participation eligibility reviewed
- Alternative resources activated

## Real-World Integration

### OpenADR Integration
```python
import aiohttp

async def send_openadr_event(participants: list, target_reduction: float):
    async with aiohttp.ClientSession() as session:
        for participant in participants:
            await session.post(
                f"https://openadr-vtn.example.com/oadrCreateEvent",
                headers={"Content-Type": "application/xml"},
                data=f"""
                <oadrPayload>
                    <oadrSignedObject>
                        <oadrEvent>
                            <eventID>{event_id}</eventID>
                            <venID>{participant['id']}</venID>
                            <oadrSignals>
                                <oadrSignal>
                                    <signalName>LOAD_CONTROL</signalName>
                                    <signalType>level</signalType>
                                    <currentValue>{target_reduction}</currentValue>
                                </oadrSignal>
                            </oadrSignals>
                        </oadrEvent>
                    </oadrSignedObject>
                </oadrPayload>
                """
            )
```

### Smart Meter API
```python
async def monitor_smart_meters(participant_ids: list):
    async with aiohttp.ClientSession() as session:
        response = await session.post(
            "https://ami.utility.com/api/v1/realtime-data",
            json={
                "meter_ids": participant_ids,
                "interval_seconds": 15,
                "metrics": ["active_power_kw", "reactive_power_kvar"]
            }
        )
        return await response.json()
```

### Grid Operator Settlement
```python
async def settle_with_iso(event_id: str, total_payment: float):
    async with aiohttp.ClientSession() as session:
        response = await session.post(
            "https://caiso.com/api/settlement",
            headers={"Authorization": "Bearer <token>"},
            json={
                "event_id": event_id,
                "program": "demand_response",
                "amount": total_payment,
                "settlement_type": "ACH"
            }
        )
        return await response.json()
```

## Testing

```bash
# Run with default settings
python examples/smart_grid_energy/main.py

# Test with different event parameters
python -c "
import asyncio
from examples.smart_grid_energy.main import SmartGridEnergySaga

async def test():
    saga = SmartGridEnergySaga(
        event_id='DR-TEST-001',
        grid_operator_id='GRID-TEST',
        target_reduction_mw=3.0,  # Larger event
        event_duration_hours=6,
        incentive_rate_per_kwh=0.20,  # Higher incentive
        simulate_failure=False
    )
    result = await saga.run({'event_id': saga.event_id})
    print(f'Result: {result}')

asyncio.run(test())
"
```

## Related Examples

- **IoT Device Orchestration** - Multi-device coordination patterns
- **Supply Chain Drone Delivery** - Real-time resource management
- **Healthcare Patient Onboarding** - Compliance and audit trails

## Best Practices

1. **Always forecast demand accurately** - Use ML models with recent data
2. **Over-recruit participants** - Account for opt-outs and non-compliance
3. **Monitor in real-time** - Detect issues early and adjust
4. **Verify before paying** - Ensure reduction targets met
5. **Maintain audit trail** - All events logged for regulatory compliance
6. **Test communication systems** - OpenADR infrastructure critical
7. **Have backup resources** - Battery storage, generators for emergencies

## Grid Operator Programs

### CAISO (California ISO)
- Proxy Demand Response (PDR)
- Reliability Demand Response Resource (RDRR)
- Peak Time Rebate Program

### PJM Interconnection
- Economic Demand Response
- Emergency Load Response
- Annual Demand Response

### ERCOT (Texas)
- Emergency Response Service (ERS)
- Load Resources
- Controllable Load Resources

## Performance Metrics

- **Response Time**: < 10 minutes from event signal to load reduction
- **Compliance Rate**: Target 90%+ participant compliance
- **Measurement Accuracy**: ±2% using smart meter data
- **Settlement Speed**: Payments within 30 days of event

---

**Questions?** Check the [main documentation](../../README.md) or open an issue.

**Disclaimer**: This is a demonstration example. Production demand response programs require ISO/RTO registration, certified measurement systems, and regulatory compliance.
