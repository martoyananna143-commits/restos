from . import (
    analytics,
    criterion,
    criterion_set,
    employee,
    evaluation,
    export,
    greeting,
    help,
    organization,
)


def all_dialogs():
    all_dialogs = (
        *greeting.greeting_dialogs(),
        help.help_dialog(),
        *organization.organization_dialogs(),
        *employee.employee_dialogs(),
        *criterion.criterion_dialogs(),
        *criterion_set.criterion_set_dialogs(),
        evaluation.evaluation_dialog(),
        export.export_dialog(),
        *analytics.analytics_dialogs(),
    )
    for dialog_position in range(len(all_dialogs)):
        dialog = all_dialogs[dialog_position]
        dialog.message(flags={"rate_limit": {"rate": 5}})
    return all_dialogs
