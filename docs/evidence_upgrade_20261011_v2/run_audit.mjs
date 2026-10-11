import {readFileSync} from 'node:fs';
import {auditConnections} from './audit.mjs';
const input=JSON.parse(readFileSync(process.argv[2]??new URL('./audit_input.json',import.meta.url),'utf8'));
const result=auditConnections(input);
console.log(JSON.stringify(result,null,2));
