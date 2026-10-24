"""Run the panel's real save handler with responses held until the user acts again."""

from __future__ import annotations

import pytest

from tests.test_a_refusal_is_not_an_answer import run

STUBS = """
let _bd={project:'acme',card:null,form:null,sig:null};
const requests=[],pending=[],opened=[];let refreshes=0;
function act(name,params){requests.push({name,params});
  return new Promise((resolve,reject)=>pending.push({resolve,reject}))}
function _bbody(){return '## Objective\\nKeep it'}
function _bpaintGate(){}
async function refreshBoard(){refreshes++}
async function boardOpenCard(ref){opened.push(ref)}
nodes['#b_save']={disabled:false};
nodes['#boardview .drawer']={innerHTML:'',classList:{add(){}},setAttribute(){}};
"""


def saved(scenario: str) -> dict:
    return run(scenario, "_blank", "boardSaveCard", "paintForm", stubs=STUBS)


@pytest.mark.parametrize("mode", ["new", "edit"])
def test_a_second_save_while_the_first_is_pending_sends_nothing(mode):
    got = saved(f"""
      const f=_bd.form=_blank('{mode}');f.title='Keep it';
      if(f.mode==='edit')_bd.card='7';
      const first=boardSaveCard();const second=boardSaveCard();await second;
      const whilePending={{count:requests.length,disabled:nodes['#b_save'].disabled}};
      paintForm();const html=nodes['#boardview .drawer'].innerHTML;
      pending[0].resolve({{ok:true,data:{{issue:'8'}}}});await first;
      return {{whilePending,html,requests,opened,form:_bd.form,refreshes}};
    """)

    assert got["whilePending"] == {"count": 1, "disabled": True}
    assert 'onclick="boardSaveCard()" disabled' in got["html"]
    assert got["requests"] == [{
        "name": "card_create" if mode == "new" else "card_edit",
        "params": {"project": "acme", "title": "Keep it", "body": "## Objective\nKeep it",
                   **({"issue": "7"} if mode == "edit" else {})},
    }]
    assert got["form"] is None
    assert got["opened"] == (["8"] if mode == "new" else [])
    assert got["refreshes"] == (0 if mode == "new" else 1)


@pytest.mark.parametrize("failure", ["refusal", "network"])
def test_a_failed_save_keeps_the_form_and_allows_a_retry(failure):
    answer = ("pending[0].reject(new Error('network unavailable'))" if failure == "network"
              else "pending[0].resolve({ok:false,message:'board unavailable'})")
    got = saved(f"""
      const f=_bd.form=_blank('new');f.title='Keep it';
      const first=boardSaveCard();{answer};await first;
      const afterFailure={{same:_bd.form===f,saving:f.saving,
                          disabled:nodes['#b_save'].disabled,title:f.title}};
      const retry=boardSaveCard();pending[1].resolve({{ok:true,data:{{issue:'9'}}}});await retry;
      return {{afterFailure,count:requests.length,opened,toasts}};
    """)

    assert got["afterFailure"] == {
        "same": True, "saving": False, "disabled": False, "title": "Keep it",
    }
    assert got["count"] == 2 and got["opened"] == ["9"]
    assert got["toasts"][0] == [
        "Not opened", "network unavailable" if failure == "network" else "board unavailable", "err",
    ]


@pytest.mark.parametrize("navigation", ["form", "project", "card"])
@pytest.mark.parametrize("answer", [
    "{ok:true,data:{issue:'8'}}",
    "{ok:false,message:'partially applied',data:{changed:'title'}}",
])
def test_a_save_response_cannot_replace_a_form_or_card_opened_meanwhile(navigation, answer):
    change = {
        "form": "_bd.form=_blank('new');_bd.form.title='Newer draft'",
        "project": "_bd.project='other'",
        "card": "_bd.card='9'",
    }[navigation]
    got = saved(f"""
      const f=_bd.form=_blank('edit');f.title='Keep it';_bd.card='7';
      const first=boardSaveCard();{change};
      const newer=_bd.form;pending[0].resolve({answer});await first;
      return {{same:_bd.form===newer,title:_bd.form.title,project:_bd.project,
               card:_bd.card,opened,refreshes,oldSaving:f.saving}};
    """)

    assert got["same"] and got["opened"] == [] and got["refreshes"] == 0
    assert got["title"] == ("Newer draft" if navigation == "form" else "Keep it")
    assert got["project"] == ("other" if navigation == "project" else "acme")
    assert got["card"] == ("9" if navigation == "card" else "7")
    assert got["oldSaving"] is False


def test_a_partially_applied_edit_still_refreshes_the_card_as_saved():
    got = saved("""
      _bd.form=_blank('edit');_bd.form.title='Keep it';_bd.card='7';
      const first=boardSaveCard();
      pending[0].resolve({ok:false,message:'body failed',data:{changed:'title'}});await first;
      return {form:_bd.form,refreshes,toasts};
    """)

    assert got == {"form": None, "refreshes": 1,
                   "toasts": [["Partly changed", "body failed", "err"]]}


def test_a_blank_title_still_refuses_without_sending_a_request():
    got = saved("""
      const f=_bd.form=_blank('new');f.title='  ';await boardSaveCard();
      return {count:requests.length,saving:f.saving,disabled:nodes['#b_save'].disabled,toasts};
    """)

    assert got == {"count": 0, "saving": False, "disabled": False,
                   "toasts": [["Not saved", "say what the card is called", "err"]]}
