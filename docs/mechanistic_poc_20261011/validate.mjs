
const CATEGORIES=new Set(["sufficient_evidence","partial_evidence","rejected_control"]);
const KINDS=new Set(["RNA_expression","protein_expression","exact_CpG_DNA_methylation","promoter_region_DNA_methylation","global_DNA_methylation"]);
function assert(ok,message){if(!ok)throw new Error(message);}
function validatePacket(p){
 assert(p.schema_version==="nutriomics-mechanistic-poc-v1","schema_version");
 assert(Array.isArray(p.cases)&&p.cases.length===10,"expected_ten_cases");
 assert(new Set(p.cases.map(c=>c.id)).size===10,"duplicate_case_id");
 assert(p.current_panel.count===50&&p.current_panel.rows.length===50,"panel_denominator");
 assert(new Set(p.current_panel.rows.map(r=>r.cpg)).size===50,"panel_duplicates");
 const panelNative=new Set(p.current_panel.native_genes),rowNative=new Set(p.current_panel.rows.flatMap(r=>r.native_genes));
 assert(panelNative.size===22&&rowNative.size===22&&[...rowNative].every(g=>panelNative.has(g)),"panel_native_annotation_receipt");
 assert(p.current_panel.rows.filter(r=>r.native_genes.length>0).length===39,"panel_annotated_denominator");
 assert(![...rowNative].some(g=>["Body","TSS200","TSS1500","1stExon","5'UTR","3'UTR"].includes(g)),"region_is_not_gene");
 const sources=new Map(p.sources.map(s=>[s.id,s]));assert(sources.size===p.sources.length,"source_duplicates");
 const panelSet=new Set(p.current_panel.rows.map(r=>r.cpg)),summary={sufficient_evidence:0,partial_evidence:0,rejected_control:0};
 for(const c of p.cases){
 assert(CATEGORIES.has(c.category),"category:"+c.id);summary[c.category]++;
 assert(c.food&&typeof c.food.identity==="string"&&Object.hasOwn(c.food,"preparation"),"food_context:"+c.id);
 assert(c.components?.length>0&&c.contexts?.length>0&&c.molecular?.length>0,"missing_mechanism:"+c.id);
 assert(c.clinical_chain_qualified===false&&c.full_causal_chain_verified===false&&c.gene_to_health_mediation_proven===false,"unsupported_qualification:"+c.id);
 assert(c.rights?.public_metadata_approved===true&&c.rights.raw_text===false&&c.rights.raw_tables===false&&c.rights.figures===false&&c.rights.individual_data===false&&!c.raw_upstream_export,"export_scope:"+c.id);
 for(const context of c.contexts)assert(context.design&&Object.hasOwn(context,"n")&&Object.hasOwn(context,"dose")&&Object.hasOwn(context,"duration")&&context.tissue&&Array.isArray(context.taxon_ids),"study_context:"+c.id);
 const exact=[];
 for(const m of c.molecular){assert(KINDS.has(m.kind)&&Array.isArray(m.targets)&&typeof m.direction==="string","molecular_kind:"+c.id);for(const s of m.source_ids)assert(sources.has(s),"missing_molecular_source:"+s);if(m.kind==="exact_CpG_DNA_methylation"){assert(m.cpgs?.length>0&&m.cpgs.every(g=>/^cg[0-9]{8}$/.test(g)),"missing_exact_cpg:"+c.id);exact.push(...m.cpgs);}else assert(!(m.cpgs??[]).length,"fabricated_exact_cpg:"+c.id);}
 assert(new Set(c.edges.map(e=>e.kind)).size===3&&["food_component","component_molecular","molecular_health"].every(k=>c.edges.some(e=>e.kind===k)),"edge_coverage:"+c.id);
 for(const e of c.edges){assert(e.direct_mediation_proven===false,"mediation_inferred:"+c.id);assert(Array.isArray(e.source_ids),"edge_sources:"+c.id);for(const id of e.source_ids)assert(sources.has(id),"unresolved_edge_source:"+id);assert(e.source_ids.length>0||/missing/.test(e.status),"unsupported_unsourced_edge:"+c.id);}
 for(const id of c.health.source_ids)assert(sources.has(id),"health_source:"+id);
 assert(c.health.mediated_by_selected_molecular_targets===false&&c.health.clinical_prevention_proven===false,"health_promotion:"+c.id);
 const unique=[...new Set(exact)],hits=unique.filter(g=>panelSet.has(g));
 assert(JSON.stringify([...c.panel_overlap.selected_exact_cpg_ids].sort())===JSON.stringify(unique.sort()),"cpg_scope:"+c.id);
 assert(JSON.stringify([...c.panel_overlap.exact_cpg_hits].sort())===JSON.stringify(hits.sort()),"cpg_overlap:"+c.id);
 assert(c.panel_overlap.exact_cpg_overlap_count===(unique.length?hits.length:null),"cpg_overlap_denominator:"+c.id);
 assert(c.panel_overlap.canonical_gene_overlap===null,"unverified_canonical_join:"+c.id);
 assert(Array.isArray(c.gaps)&&c.gaps.length>0&&c.negative_checks.length>0,"missing_limits:"+c.id);
 }
 assert(p.global_limits.full_causal_or_clinical_qualified_cases===0&&p.global_limits.full4630linked_structures===null&&p.global_limits.full4630unverified_structures===null,"full_catalogue_or_clinical_claim");
 return{valid:true,cases:p.cases.length,sources:p.sources.length,panel_cpgs:50,categories:summary,causal_or_clinical_qualified:0,exact_selected_cpgs:[...new Set(p.cases.flatMap(c=>c.panel_overlap.selected_exact_cpg_ids))],exact_selected_cpg_hits:[...new Set(p.cases.flatMap(c=>c.panel_overlap.selected_exact_cpg_ids))].filter(cg=>panelSet.has(cg)),canonical_gene_overlap:null};
}
function assessClaim(p,claim){
 const c=p.cases.find(c=>c.id===claim.poc_id),reasons=[];
 if(!c)return{accepted:false,reasons:["unknown_poc_id"]};
 const allowed=new Set(["poc_id","clinical_chain_qualified","full_causal_chain_verified","gene_to_health_mediation_proven","isolated_compound_causal_effect_proven","raw_upstream_export","food_preparation","component_name","canonical_gene_overlap","molecular_kind","specific_cpg","direction","molecular_index","subject_n","cross_study_hypothesis","panel_exact_cpg_overlap_count","health_claim","individual_hydroxytyrosol_dose","health_source_DOI"]);for(const key of Object.keys(claim))if(!allowed.has(key))reasons.push("unknown_claim_field:"+key);
 for(const key of ["clinical_chain_qualified","full_causal_chain_verified","gene_to_health_mediation_proven","isolated_compound_causal_effect_proven"])if(claim[key]===true&&!c[key])reasons.push("unsupported:"+key);
 if(claim.raw_upstream_export===true)reasons.push("raw_export_not_authorized");
 if(Object.hasOwn(claim,"food_preparation")&&claim.food_preparation!==c.food.preparation)reasons.push("different_food_preparation");
 if(Object.hasOwn(claim,"component_name")&&!c.components.some(k=>k.native_name===claim.component_name))reasons.push("different_native_component");
 if(Object.hasOwn(claim,"canonical_gene_overlap")&&claim.canonical_gene_overlap!==null)reasons.push("canonical_mapping_unavailable");
 if(claim.molecular_kind&&!c.molecular.some(m=>m.kind===claim.molecular_kind))reasons.push("assay_type_mismatch");
 if(claim.specific_cpg&&!c.panel_overlap.selected_exact_cpg_ids.includes(claim.specific_cpg))reasons.push("cpg_not_assayed");
 if(Object.hasOwn(claim,"direction")){const m=c.molecular[claim.molecular_index??0];if(!m||claim.direction!==m.direction)reasons.push("direction_mismatch");}
 if(Object.hasOwn(claim,"subject_n")){const n=c.expected_subject_n[claim.molecular_kind];if(n==null||claim.subject_n!==n)reasons.push("subject_scope_or_n_unverified");}
 if(Object.hasOwn(claim,"cross_study_hypothesis")&&claim.cross_study_hypothesis!==c.cross_study_hypothesis)reasons.push("bridge_scope_mismatch");
 if(Object.hasOwn(claim,"panel_exact_cpg_overlap_count")&&claim.panel_exact_cpg_overlap_count!==c.panel_overlap.exact_cpg_overlap_count)reasons.push("panel_overlap_mismatch");
 if(claim.health_claim&&!["source_reported_observation","disease_prevention","fasting_microvascular_improvement","fracture_prevention_proven"].includes(claim.health_claim))reasons.push("unknown_health_claim");
 if(claim.health_claim==="disease_prevention")reasons.push("disease_prevention_not_established_by_mechanistic_chain");
 if(c.id==="P03"&&claim.health_claim==="fasting_microvascular_improvement")reasons.push("fasting_endpoint_not_significant");
 if(c.id==="P07"&&claim.health_claim==="fracture_prevention_proven")reasons.push("fracture_ITT_CI_includes_one");
 if(c.id==="P04"&&claim.individual_hydroxytyrosol_dose!=null)reasons.push("hydroxytyrosol_unit_unreconciled");
 if(c.id==="P08"&&claim.health_source_DOI==="10.1056/NEJMoa1200303")reasons.push("use_corrected_2018_health_report");
 return{accepted:reasons.length===0,reasons};
}
function expectedCards(p){validatePacket(p);return p.cases.map(c=>({poc_id:c.id,title:c.title,category:c.category,molecular_kinds:[...new Set(c.molecular.map(m=>m.kind))],native_food:c.food,native_components:c.components.map(x=>x.native_name),selected_targets:c.molecular.map(m=>({kind:m.kind,targets:m.targets,cpgs:m.cpgs??[],direction:m.direction})),health_observation:c.health,cross_study_hypothesis:c.cross_study_hypothesis,panel_overlap:c.panel_overlap,source_ids:[...new Set(c.edges.flatMap(e=>e.source_ids).concat(c.molecular.flatMap(m=>m.source_ids),c.health.source_ids))],clinical_chain_qualified:false,full_causal_chain_verified:false,export_scope:"citation_and_new_factual_metadata_only",limitations:c.gaps}));}
export {validatePacket,assessClaim,expectedCards};
