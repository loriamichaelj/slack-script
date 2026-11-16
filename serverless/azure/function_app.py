"""Azure Functions entry point: one timer trigger per job, all running the same code as Lambda.

The schedules are NCRONTAB (second minute hour day month weekday) in UTC, because Linux
function plans have no time zone setting. 14:00 and 14:30 UTC are 9:00 and 9:30 in New York
in winter, and an hour later in summer.

A failed run raises, so the host records it. There is no retry: a retry could post the same
alert twice, and the next run picks up what was missed.
"""

import azure.functions as func

from anomaly_alerts.handler import run_event

app = func.FunctionApp()

JOBS = {
    "anomaly_run": ("0 */5 * * * *", {"command": "run"}),
    "routine_heartbeat": ("0 0 */6 * * *", {"command": "routine", "kind": "heartbeat"}),
    "routine_digest": ("0 0 14 * * *", {"command": "routine", "kind": "digest"}),
    "routine_cost": ("0 30 14 * * *", {"command": "routine", "kind": "cost"}),
}


def _register(name: str, schedule: str, event: dict):
    @app.function_name(name=name)
    @app.timer_trigger(schedule=schedule, arg_name="timer", run_on_startup=False, use_monitor=False)
    def job(timer: func.TimerRequest) -> None:
        run_event(event)

    return job


for _name, (_schedule, _event) in JOBS.items():
    _register(_name, _schedule, _event)
