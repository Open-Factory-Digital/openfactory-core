"""Each read route declares its model and the body it sends is unchanged by it (#678, slice a),
proven by breaking it.

Run:  .venv/bin/python tools/mutate.py tools/mutations/the_read_routes_declare_their_model.py

The claims, each a row:
  1. a key no model names reaches the client as it did;
  2. an integral number in an `int | float` field is sent as the route computed it;
  3. a key a route leaves out stays out;
  4. a row that lacks a field is answered, never refused;
  5. every listed route declares a model.
"""

TEST = "tests/test_the_read_routes_declare_their_model.py"
MODELS = "openfactory/api/read_models.py"
APP = "openfactory/api/app.py"

MUTATIONS = [
    # 1. what no model names
    ("a model drops the keys it does not name", MODELS,
     '    model_config = ConfigDict(extra="allow")',
     '    model_config = ConfigDict(extra="ignore")'),

    # 2. a number as computed
    ("an integral count is sent as a float", MODELS,
     "Number = int | float\n",
     "Number = float\n"),

    # 3. what a route leaves out
    ("a field's default is written into a body that did not carry it", APP,
     '    return {"response_model": model, "response_model_exclude_unset": True}',
     '    return {"response_model": model, "response_model_exclude_unset": False}'),

    # 4. a row that lacks a field
    ("a budget row without an error is refused", MODELS,
     "    reset_at: str | None = None\n    error: str | None = None\n",
     "    reset_at: str | None = None\n    error: str | None\n"),

    # 5. the declaration itself
    ("the budget is declared without a model", APP,
     '@_read("/api/budget", read_models.BudgetRead)',
     '@app.get("/api/budget")'),
]
