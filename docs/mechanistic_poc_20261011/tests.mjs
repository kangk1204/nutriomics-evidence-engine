import {readFile} from "node:fs/promises";
import {validatePacket,assessClaim,expectedCards} from "./validate.mjs";

function runTests(packet,negativeFixtures){
 const tests=[],test=(name,fn)=>{try{fn();tests.push({name,passed:true});}catch(e){tests.push({name,passed:false,error:String(e.message??e)});}};
 const ok=(b,msg="assertion")=>{if(!b)throw new Error(msg);};const copy=x=>JSON.parse(JSON.stringify(x));const throws=fn=>{let done=false;try{fn();}catch{done=true;}ok(done,"expected rejection");};
 test("actual_ten_case_packet_validates",()=>ok(validatePacket(packet).valid));
 test("actual50panel_and_four_selected_exact_nonoverlappingCpGs",()=>{const r=validatePacket(packet);ok(r.panel_cpgs===50&&r.exact_selected_cpgs.length===4&&r.exact_selected_cpg_hits.length===0&&r.canonical_gene_overlap===null);});
 for(const c of packet.cases){
 test(c.id+":source_backed_card_and_limits",()=>{const card=expectedCards(packet).find(x=>x.poc_id===c.id);ok(card.source_ids.length>0&&card.limitations.length>0&&!card.clinical_chain_qualified&&!card.full_causal_chain_verified);});
 test(c.id+":native_assay_direction_accepted",()=>{const m=c.molecular[0];ok(assessClaim(packet,{poc_id:c.id,molecular_kind:m.kind,direction:m.direction,food_preparation:c.food.preparation,cross_study_hypothesis:c.cross_study_hypothesis}).accepted);});
 test(c.id+":raw_export_is_rejected",()=>ok(!assessClaim(packet,{poc_id:c.id,raw_upstream_export:true}).accepted));
 test(c.id+":mediation_promotion_is_rejected",()=>ok(!assessClaim(packet,{poc_id:c.id,gene_to_health_mediation_proven:true}).accepted));
 }
 for(const f of negativeFixtures)test(f.id+":"+f.expected_reason,()=>{const r=assessClaim(packet,f.claim);ok(r.accepted===false&&r.reasons.includes(f.expected_reason));});
 test("duplicate_case_identity_rejected",()=>{const p=copy(packet);p.cases[1].id=p.cases[0].id;throws(()=>validatePacket(p));});
 test("source_fk_conflict_rejected",()=>{const p=copy(packet);p.cases[0].molecular[0].source_ids=["missingSource"];throws(()=>validatePacket(p));});
 test("fabricated_CpG_on_global_methylation_rejected",()=>{const p=copy(packet);p.cases.find(c=>c.id==="P05").molecular[0].cpgs=["cg21094739"];throws(()=>validatePacket(p));});
 test("unknown_assay_kind_rejected",()=>{const p=copy(packet);p.cases[0].molecular[0].kind="unknown";throws(()=>validatePacket(p));});
 test("clinical_qualification_in_packet_rejected",()=>{const p=copy(packet);p.cases[0].clinical_chain_qualified=true;throws(()=>validatePacket(p));});
 test("unsupported_canonical_count_in_packet_rejected",()=>{const p=copy(packet);p.cases[0].panel_overlap.canonical_gene_overlap=0;throws(()=>validatePacket(p));});
 test("full4630join_in_packet_rejected",()=>{const p=copy(packet);p.global_limits.full4630linked_structures=10;throws(()=>validatePacket(p));});
 test("panel_overlap_mutation_rejected",()=>{const p=copy(packet);p.cases.find(c=>c.id==="P08").panel_overlap.exact_cpg_overlap_count=2;throws(()=>validatePacket(p));});
 test("unknown_POC_claim_rejected",()=>ok(!assessClaim(packet,{poc_id:"P99"}).accepted));
 test("same_registered_trial_not_independent_replication",()=>{const c=packet.cases.find(c=>c.id==="P03");ok(c.independent_replication_count===null&&c.contexts[0].n.RNA_substudy===10&&c.contexts[0].n.enrolled===24);});
 test("only_selected_targets_checked_not_whole3422transcriptome",()=>ok(packet.cases.find(c=>c.id==="P03").panel_overlap.scope.includes("not entire")));
 test("three_rejected_controls_remain_in_output",()=>ok(expectedCards(packet).filter(c=>c.category==="rejected_control").length===3));

 test("unknown_claim_fields_do_not_silently_pass",()=>ok(assessClaim(packet,{poc_id:"P06",cancer_cure:true}).reasons.includes("unknown_claim_field:cancer_cure")));
 test("unknown_health_claim_does_not_silently_pass",()=>ok(assessClaim(packet,{poc_id:"P06",health_claim:"cancer_cure"}).reasons.includes("unknown_health_claim")));
 test("computed_selected_hit_is_not_hardcoded_zero",()=>{const p=copy(packet),row=p.current_panel.rows[0];row.cpg="cg01081346";const c=p.cases.find(c=>c.id==="P08");c.panel_overlap.exact_cpg_hits=["cg01081346"];c.panel_overlap.exact_cpg_overlap_count=1;const r=validatePacket(p);ok(r.exact_selected_cpg_hits.length===1&&r.exact_selected_cpg_hits[0]==="cg01081346"&&r.causal_or_clinical_qualified===0);});
 test("native22genes_and39annotated_rows_exclude_region_labels",()=>{const pgenes=new Set(packet.current_panel.rows.flatMap(r=>r.native_genes));ok(pgenes.size===22&&packet.current_panel.rows.filter(r=>r.native_genes.length).length===39&&!pgenes.has("Body"));});
 test("region_label_accidentally_parsed_as_gene_is_rejected",()=>{const p=copy(packet);p.current_panel.rows[0].native_genes=["Body"];throws(()=>validatePacket(p));});
 test("completed_visits_are_not_per_gene_analyzable_n",()=>{const c=packet.cases.find(c=>c.id==="P02");ok(c.contexts[0].n.completed===15&&c.contexts[0].n.sputum_neutrophil_endpoint===14&&c.expected_subject_n.RNA_expression===null);ok(!assessClaim(packet,{poc_id:"P02",molecular_kind:"RNA_expression",subject_n:15}).accepted);});
 test("randomized_total_is_not_exact_IHC_marker_pair_count",()=>ok(!assessClaim(packet,{poc_id:"P06",molecular_kind:"protein_expression",subject_n:32}).accepted));
 return{runtime:"JavaScript V8 through functions.exec",scope:"actual curated10-case metadata consistency plus synthetic output-boundary QA; not independent biological accuracy or API HTTP/UI testing",count:tests.length,passed:tests.every(t=>t.passed),tests};
}

const packet=JSON.parse(await readFile(new URL("./pocs.json",import.meta.url),"utf8"));
const fixtures=JSON.parse(await readFile(new URL("./negative_fixtures.json",import.meta.url),"utf8"));
const result=runTests(packet,fixtures);
result.runtime="Node.js "+process.version;
console.log(JSON.stringify(result,null,2));
process.exitCode=result.passed?0:1;
