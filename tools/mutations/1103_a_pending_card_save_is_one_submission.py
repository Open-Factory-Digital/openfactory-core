"""A slow card save sends once, recovers after failure, and stays with its original form."""

TEST = "tests/test_a_pending_card_save_is_one_submission.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    ("a second click sends the same pending card again", PANEL,
     "  const f = _bd.form; if(!f || f.saving) return;",
     "  const f = _bd.form; if(!f) return;"),
    ("save stays visibly enabled while the request is pending", PANEL,
     '  const save = $("#b_save"); if(save) save.disabled = true;',
     '  const save = $("#b_save"); if(save) save.disabled = false;'),
    ("repainting a pending form enables its save button", PANEL,
     'onclick="boardSaveCard()"${f.saving ? " disabled" : ""}>save</button>',
     'onclick="boardSaveCard()">save</button>'),
    ("a failed request leaves the form permanently pending", PANEL,
     "  f.saving = false;\n  if(_bd.form !== f",
     "  f.saving = true;\n  if(_bd.form !== f"),
    ("an old save closes a different form or navigates away from the selected card", PANEL,
     "  if(_bd.form !== f || _bd.project !== project || _bd.card !== card) return;",
     "  if(false) return;"),
    ("a failed request leaves its save control disabled", PANEL,
     '  const currentSave = $("#b_save"); if(currentSave) currentSave.disabled = false;',
     '  const currentSave = $("#b_save"); if(currentSave) currentSave.disabled = true;'),
    ("a network failure escapes without keeping a retryable form", PANEL,
     '  } catch(e){ r = {ok:false, message:e.message||"the card could not be saved"}; }',
     "  } catch(e){ throw e; }"),
]
