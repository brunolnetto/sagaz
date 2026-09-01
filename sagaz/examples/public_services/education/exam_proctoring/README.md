# Exam Proctoring Saga

This example demonstrates an **exam start pivot point** in an online proctoring system. Once the exam timer starts, the student is committed to the exam session.

## Pivot Point

**Step:** `start_exam`

Once the exam starts:
- The exam timer is running
- The exam attempt is logged in the academic record
- Questions are revealed (cannot be "unseen")
- The student must complete or forfeit the attempt

## Saga Steps

```
┌─────────────────────────────────────────────────────────────────┐
│                     REVERSIBLE ZONE                              │
├─────────────────────────────────────────────────────────────────┤
│  verify_student → check_environment → reserve_exam_slot          │
│                                                                  │
│  Student can cancel before exam starts                          │
├─────────────────────────────────────────────────────────────────┤
│                    ↓ PIVOT BOUNDARY ↓                            │
├─────────────────────────────────────────────────────────────────┤
│                     COMMITTED ZONE                               │
│                                                                  │
│  🔒 start_exam (PIVOT) → monitor_session → submit_exam          │
│                                                                  │
│  Exam attempt recorded - forward recovery only                   │
└─────────────────────────────────────────────────────────────────┘
```

## Forward Recovery

If monitoring fails during the exam:
- **RETRY**: Pause exam timer, notify proctor, resume after fix
- Never abandon a started exam - student's grade is at stake

## Running the Example

```bash
cd examples/education/exam_proctoring
python main.py
```

## Key Features Demonstrated

- `@action("start_exam", pivot=True)` - Marks exam start as irreversible
- `@forward_recovery("monitor_session")` - Handles technical issues during exam
- Real-time event that cannot be replayed

## Business Context

In academic proctoring:
- Identity verification prevents impersonation
- Environment checks ensure exam integrity
- Starting the exam creates an official attempt record
- Technical issues must not invalidate the student's work
- Webcam and screen monitoring must continue throughout
