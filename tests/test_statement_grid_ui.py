"""Exercise the grid form's actual JS submit handler with a small DOM boundary."""

import json
from pathlib import Path
import subprocess


def submit_grid(values, use_candidate=False, margin_candidate=False):
    suite = Path(__file__).parents[1] / "ifms_suite" / "static" / "suite.js"
    script = r"""
const fs=require('fs'),vm=require('vm');
const source=fs.readFileSync(process.argv[1],'utf8');
const start=source.indexOf('function renderStatementGrid(id,grid) {');
const end=source.indexOf('\nlet documentRecordsRequest=',start);
const inputs=JSON.parse(process.argv[2]).map((value,column)=>({value,dataset:{row:'0',column:String(column)},addEventListener(){},focus(){this.focused=true;}}));
const marginInputs=[{value:'',dataset:{gridMargin:'0'},addEventListener(){},focus(){this.focused=true;}}];
const marginButtons=[{dataset:{marginRegion:'0',candidateIndex:'1'},addEventListener(type,handler){this[type]=handler;}}];
const candidateButtons=[{dataset:{row:'0',column:'1',candidateIndex:'1'},addEventListener(type,handler){this[type]=handler;}}];
const elements={statementGridResult:{querySelectorAll(selector){return selector.includes('data-grid-margin')?marginInputs:selector.includes('data-margin-candidate')?marginButtons:selector.includes('data-grid-candidate')?candidateButtons:inputs;},querySelector(selector){return selector.includes('data-grid-margin')?marginInputs[0]:inputs[1];}},
 gridSourceImage:{},gridMarginCorrections:{elements:{reference:{value:'Original margin checked'},reviewed:{checked:true}}},gridCellCorrections:{elements:{reference:{value:'Original page checked'},reviewed:{checked:true}}},gridColumnMapping:{}};
const posts=[],notices=[];
const grid={source_page:1,source_sha256:'sha',grid_revision:'grid',correction_revision:0,table_rows:[['Jul-2026','120','']],editable_rows:[['Jul-2026','120','']],editable_margin_regions:[{region_id:'right_margin_r0',row:0,editable_text:null,candidates:[{text:'1O0'},{text:'100'}]}],cells:[{row:0,column:1,text:null,candidates:[{text:'1O0'},{text:'100'}]}]};
const context={console,Map,Set,Array,Number,Object,String,escapeHTML:v=>String(v??''),$:id=>elements[id],post:async(path,payload)=>{posts.push(payload);return grid;},notify:message=>notices.push(message)};
vm.createContext(context);vm.runInContext(source.slice(start,end),context);
context.renderStatementGrid(1,grid);
(async()=>{if(process.argv[3]==='candidate'){if(!candidateButtons[0].click)throw Error('Raw candidate has no use button handler');candidateButtons[0].click();if(!inputs[1].focused)throw Error('Selected input was not focused');if(posts.length)throw Error('Candidate selection saved without review');}if(process.argv[3]==='margin'){if(!marginButtons[0].click)throw Error('Margin candidate has no use handler');marginButtons[0].click();if(!marginInputs[0].focused)throw Error('Margin input not focused');if(posts.length)throw Error('Margin selection saved without review');await elements.gridMarginCorrections.onsubmit({preventDefault(){},stopPropagation(){}});}else{await elements.gridCellCorrections.onsubmit({preventDefault(){},stopPropagation(){}});}console.log(JSON.stringify({posts,notices}));})().catch(e=>{console.error(e);process.exit(1);});
"""
    result = subprocess.run(
        [
            "node",
            "-e",
            script,
            str(suite),
            json.dumps(values),
            "margin" if margin_candidate else "candidate" if use_candidate else "save",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_standalone_save_only_sends_changed_cells_leaving_untouched_blanks_alone():
    result = submit_grid(["Jul-2026", "125", ""])
    assert result["posts"][0]["corrections"] == [{"row": 0, "column": 1, "text": "125"}]
    assert result["posts"][0]["reviewed"] is True


def test_unchanged_grid_shows_help_instead_of_creating_audit_noise():
    result = submit_grid(["Jul-2026", "120", ""])
    assert result["posts"] == []
    assert any("change" in notice.lower() for notice in result["notices"])


def test_raw_candidate_click_copies_literal_without_saving_until_review_submit():
    result = submit_grid(["Jul-2026", "120", ""], use_candidate=True)
    assert result["posts"][0]["corrections"] == [{"row": 0, "column": 1, "text": "100"}]


def test_margin_candidate_is_saved_only_as_explicit_reviewed_annotation():
    result = submit_grid(["Jul-2026", "120", ""], margin_candidate=True)
    assert result["posts"][0]["margin_corrections"] == [
        {"region_id": "right_margin_r0", "text": "100"}
    ]
    assert "corrections" not in result["posts"][0]
    assert result["posts"][0]["reviewed"] is True
