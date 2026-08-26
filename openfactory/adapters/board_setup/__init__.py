"""The board-setup axis — the ONE-SHOT act `openfactory init` performs on a vendor that needs it.

Most trackers bring their own board: on Jira the project's workflow IS the board, on Azure Boards
the board exists with the project. GitHub is the vendor whose board is a second object that has
to be CREATED, and `cli.py` imported that vendor's module by name to do it. This axis is where a
tracker declares whether it has such an act, so the CLI asks the registry instead of naming a
vendor — and a stranger's tracker can declare one (`board_setup.<kind>`) without editing core.
"""
