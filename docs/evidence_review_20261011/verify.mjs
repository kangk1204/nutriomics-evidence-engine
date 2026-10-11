import {readFileSync} from 'node:fs';
const data=JSON.parse(readFileSync(new URL('./evidence.json',import.meta.url),'utf8'));
const schema=JSON.parse(readFileSync(new URL('./evidence.schema.json',import.meta.url),'utf8'));
function validateSchema(value,schema,path="$",errors=[]) {
  const actual=value===null?"null":Array.isArray(value)?"array":typeof value;
  if(schema.const!==undefined && JSON.stringify(value)!==JSON.stringify(schema.const)) errors.push(path+": const");
  if(schema.enum && !schema.enum.includes(value)) errors.push(path+": enum");
  if(schema.type){
    const types=Array.isArray(schema.type)?schema.type:[schema.type];
    const ok=types.some(t=>t==="integer"?typeof value==="number"&&Number.isInteger(value):t===actual);
    if(!ok){errors.push(path+": type");return errors;}
  }
  if(typeof value==="number"){
    if(schema.minimum!==undefined&&value<schema.minimum) errors.push(path+": minimum");
    if(schema.maximum!==undefined&&value>schema.maximum) errors.push(path+": maximum");
  }
  if(typeof value==="string"){
    if(schema.pattern&&!new RegExp(schema.pattern).test(value)) errors.push(path+": pattern");
    if(schema.format==="uri"&&!/^https?:\/\//.test(value)) errors.push(path+": uri");
    if(schema.format==="date-time"&&!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(value)) errors.push(path+": date-time");
  }
  if(Array.isArray(value)){
    if(schema.minItems!==undefined&&value.length<schema.minItems) errors.push(path+": minItems");
    if(schema.maxItems!==undefined&&value.length>schema.maxItems) errors.push(path+": maxItems");
    if(schema.uniqueItems&&new Set(value.map(x=>JSON.stringify(x))).size!==value.length) errors.push(path+": uniqueItems");
    if(schema.items)value.forEach((v,i)=>validateSchema(v,schema.items,path+"["+i+"]",errors));
  }
  if(actual==="object"){
    for(const k of schema.required??[])if(!(k in value))errors.push(path+"."+k+": required");
    for(const [k,v] of Object.entries(value)){
      if(schema.properties?.[k])validateSchema(v,schema.properties[k],path+"."+k,errors);
      else if(schema.additionalProperties===false) errors.push(path+"."+k+": additional");
    }
  }
  return errors;
}
function verifyPack(d,schema){
  const checks=[];
  const add=(name,ok)=>checks.push({name,passed:!!ok});
  const unique=a=>new Set(a).size;
  add("supported JSON-schema keyword checks",validateSchema(d,schema).length===0);
  add("50 exact unique CpG IDs",d.panel_rows.length===50&&unique(d.panel_rows.map(x=>x.cpg))===50);
  add("39 annotated and 11 unassigned",d.panel_rows.filter(x=>x.annotation!=="미배정").length===39&&d.panel_rows.filter(x=>x.annotation==="미배정").length===11);
  add("22 native gene labels",unique(d.native_gene_labels)===22);
  add("46 observed replication probes and 4 missing",d.panel_rows.filter(x=>x.delta_beta_replication_pp!==null).length===46);
  add("selection denominator remains15",d.panel_rows.every(x=>x.selection_denominator===15&&x.selected_folds>=0&&x.selected_folds<=15));
  add("inventory quantity partition",d.denominators.food_inventory_positive_numeric_linked_structures+d.denominators.food_inventory_qualitative_only_structures===d.denominators.food_inventory_structures);
  add("occurrence partition",d.denominators.food_inventory_measured_occurrence_rows+d.denominators.food_inventory_qualitative_occurrence_rows===d.denominators.food_inventory_total_occurrence_rows);
  add("six traces share one composition measurement",d.reviewed_traces.length===6&&unique(d.reviewed_traces.map(x=>x.composition_measurement_id))===1);
  add("five genes and five compound-gene edges",unique(d.reviewed_traces.map(x=>x.gene_symbol))===5&&unique(d.reviewed_traces.map(x=>x.compound_gene_edge_id))===5);
  add("no native panel overlap in available six traces",d.reviewed_traces.every(x=>!d.native_gene_labels.includes(x.gene_symbol))&&d.denominators.trace_panel_native_gene_overlap===0);
  add("six source bridges never promoted to exact structure",d.reviewed_traces.every(x=>x.ctd_exact_structure_verified===false&&x.binding_label===false));
  add("whole4630 linked/unverified counts remain unknown",d.denominators.current_4630_compound_to_actual_panel_linked_count===null&&d.denominators.current_4630_compound_to_actual_panel_unverified_count===null);
  add("all records remain unqualified and unapplied",d.records.every(x=>x.chain_qualified===false)&&d.scope.api_application_status==="not_applied"&&d.scope.local_report_modified===false);
  add("cell study not labelled clinical RCT",d.records.find(x=>x.record_id==="D01").study.design==="in_vitro_perturbation");
  add("PTGS2 supported increase retained",d.records.find(x=>x.record_id==="D01").effect.direction==="increases_PTGS2_protein_and_PGE2");
  add("EGCG-specific Nrf2 primary record remains unverified",d.records.find(x=>x.record_id==="D02").primary_exact_record_verified===false);
  add("nested/cotreatment caveats retained",["D03","D04","D05"].every(id=>d.records.find(x=>x.record_id===id).not_supported.length>0));
  add("prediction separated from causal direction",d.records.find(x=>x.record_id==="P01").evidence_class==="computational_prediction");
  add("FISHGASTRO ambiguity and modality retained",d.fishgastro_constraints.GEO_people===28&&d.fishgastro_constraints.conference_people===31&&!d.fishgastro_constraints.denominator_reconciled&&!d.fishgastro_constraints.individual_clinical_crosswalk_available&&d.fishgastro_constraints.nominal_genes_fail_FDR&&d.fishgastro_constraints.modality==="gene_expression_not_DNAm");
  for(const [name,mutate] of [
    ["negative: reject undocumented qualification",x=>x.records[0].chain_qualified=true],
    ["negative: reject missing dose field",x=>delete x.records[0].study.dose],
    ["negative: reject invalid CpG ID",x=>x.records[0].panel_cpgs=["cg123"]],
    ["negative: reject invented linked denominator",x=>x.denominators.current_4630_compound_to_actual_panel_linked_count=4630],
    ["negative: reject undocumented application",x=>x.scope.api_application_status="applied"]
  ]){const x=JSON.parse(JSON.stringify(d));mutate(x);add(name,validateSchema(x,schema).length>0);}
  return {runtime:"JavaScript V8 through functions.exec",schema_validator_scope:"supported keywords only, no external JSON-schema package",checks,passed:checks.every(x=>x.passed),count:checks.length,scientific_validation_claim:false,local_tests_ran:false,model_reanalysis_ran:false};
}
const result=verifyPack(data,schema);
console.log(JSON.stringify(result,null,2));
if(!result.passed)process.exitCode=1;
