"""Asked for one card, Jira and Azure DevOps say why it closed, as their summaries do (#480).

Run:  .venv/bin/python tools/mutate.py tools/mutations/480_one_card_says_why_it_closed.py

Rows 1-2 are the defect as it shipped, one per row: `get_ticket` says nothing. Rows 3-4 give an
open card a reason.
"""

TEST = "tests/test_one_card_says_why_it_closed.py"

JIRA = "openfactory/adapters/tracker/jira.py"
ADO = "openfactory/adapters/tracker/azure_devops.py"

MUTATIONS = [
    ("TODAY'S DEFECT on Jira: one card never says why it closed", JIRA,
     "        ticket.state_reason = self._closed_reason(fields) if ticket.state == \"closed\" "
     "else \"\"\n",
     ""),

    ("TODAY'S DEFECT on Azure DevOps: one card never says why it closed", ADO,
     '        ticket.state_reason = self._closed_reason(type_name, state_name) if closed else ""\n',
     ""),

    ("Jira gives an open card a reason", JIRA,
     'ticket.state_reason = self._closed_reason(fields) if ticket.state == "closed" else ""',
     "ticket.state_reason = self._closed_reason(fields)"),

    ("Azure DevOps gives an open card a reason", ADO,
     'ticket.state_reason = self._closed_reason(type_name, state_name) if closed else ""',
     "ticket.state_reason = self._closed_reason(type_name, state_name)"),
]
