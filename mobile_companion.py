"""Authenticated, LAN-only HTTPS companion for MySQL Editor.

The desktop app starts this TLS-protected service only after the user explicitly
enables it. The short-lived certificate and pairing secret are never persisted.
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import ipaddress
import json
import os
import secrets
import socket
import ssl
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from feature_governor import FeatureGovernor
from password_auth import is_password_record, verify_password

import pymysql

class RequestBodyTooLarge(ValueError):
    """Raised when an HTTP request declares a body beyond the accepted limit."""


class ResultTooLarge(ValueError):
    """Raised before a streamed CSV can exhaust the user's disk."""


APP_NAME = "MySQL Editor Mobile"
IDLE_TIMEOUT_SECONDS = 30 * 60
MAX_SESSIONS = 5
MAX_BODY_BYTES = 512 * 1024
MAX_SQL_BYTES = 256 * 1024
MAX_RESULT_BYTES = 512 * 1024 * 1024
MAX_CONCURRENT_REQUESTS = 24
FETCH_BATCH_SIZE = 64
MAX_PREVIEW_ROWS = 150
MAX_PREVIEW_COLUMNS = 60
MAX_PREVIEW_CELL_CHARS = 200
PAIR_LOCKOUT_SECONDS = 60
MAX_PAIR_FAILURES = 8


MOBILE_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#101827"><meta name="color-scheme" content="dark">
<title>MySQL Editor Mobile</title>
<style>
:root{color-scheme:dark;--bg:#0b1020;--panel:#111a2b;--line:#2a3850;--text:#edf3ff;--muted:#9eacc3;--accent:#61a8ff;--good:#66d9a7;--bad:#ff8f98}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(1000px 500px at 20% -10%,#1e3556 0%,var(--bg) 60%);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;min-height:100vh}button,input,textarea{touch-action:manipulation}button{min-height:44px}input,textarea{min-height:44px}button:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible{outline:3px solid #8ac4ff;outline-offset:2px}@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;animation:none!important;transition:none!important}}
header{padding:18px 16px 12px;border-bottom:1px solid var(--line);position:sticky;top:0;background:#0b1020ed;backdrop-filter:blur(12px);z-index:3}header .sub{color:var(--muted);font-size:12px}h1{font-size:20px;margin:0;letter-spacing:.2px}.wrap{width:min(1100px,100%);margin:auto;padding:16px;display:grid;gap:14px}.panel{background:linear-gradient(180deg,#141f32,#101827);border:1px solid var(--line);border-radius:16px;padding:16px;box-shadow:0 12px 32px #0002}.panel h2{font-size:16px;margin:0 0 12px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.field{display:flex;flex-direction:column;gap:5px;min-width:0}.field.wide{grid-column:1/-1}label{font-size:12px;color:var(--muted)}input,textarea,select{font:inherit;color:var(--text);background:#09111f;border:1px solid #34445e;border-radius:10px;padding:11px;width:100%;min-width:0;outline:none}input:focus,textarea:focus{border-color:var(--accent);box-shadow:0 0 0 2px #61a8ff22}textarea{font:13px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace;min-height:170px;resize:vertical;tab-size:4}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}button,.button{border:1px solid #3a4d69;border-radius:10px;padding:10px 14px;background:#192841;color:var(--text);font:600 14px system-ui;cursor:pointer;text-decoration:none}button.primary{background:#1d65c1;border-color:#2b81e9}button.danger{color:#ffc2c7;border-color:#78414d}button:disabled{opacity:.5;cursor:wait}.hint,.muted{color:var(--muted);font-size:12px}.status{padding:10px 12px;border-radius:10px;background:#15243a;color:var(--muted);white-space:pre-wrap;overflow-wrap:anywhere}.status.good{color:var(--good)}.status.bad{color:var(--bad)}.hidden{display:none!important}.rowhead{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}.table-wrap{overflow:auto;max-height:55vh;border:1px solid var(--line);border-radius:10px;margin-top:12px}table{border-collapse:separate;border-spacing:0;width:max-content;min-width:100%;font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace}th,td{padding:8px 10px;border-bottom:1px solid #27364b;border-right:1px solid #27364b;text-align:left;vertical-align:top;max-width:340px;overflow-wrap:anywhere;white-space:pre-wrap}th{position:sticky;top:0;background:#1b2a40;color:#cfe3ff}td{background:#101a2a}tr:nth-child(even) td{background:#131f31}.null{color:#8190a8;font-style:italic}.metrics{display:flex;gap:12px;flex-wrap:wrap;color:var(--muted);font-size:12px}.metrics strong{color:var(--text)}footer{padding:0 16px 24px;color:var(--muted);font-size:11px;text-align:center}.badge{border:1px solid #36506f;border-radius:20px;padding:3px 8px;font-size:11px;color:#bddaff}.brand{display:flex;align-items:center;gap:10px;min-width:0}.brand-logo{width:38px;height:38px;object-fit:contain;flex:none}.secret-control{display:flex;align-items:stretch;gap:6px}.secret-control input{flex:1;min-width:0}.secret-control button{flex:none;min-width:66px;padding:8px 12px}
@media(min-width:850px){.wrap{grid-template-columns:340px minmax(0,1fr);align-items:start}.editor{grid-column:2;grid-row:1/3}.connection{grid-column:1;grid-row:1}.result{grid-column:1/-1}.grid{grid-template-columns:1fr 1fr}.field.wide{grid-column:1/-1}}
@media(max-width:420px){.wrap{padding:10px}.panel{padding:12px}.grid{grid-template-columns:1fr 1fr}.field.wide{grid-column:1/-1}header{padding:14px 12px 10px}}
</style></head><body>
<header><div class="rowhead"><div class="brand"><img class="brand-logo" src="/brand/mysqlidle-logo.png" alt="MySQL Editor logo"><div><h1>MySQL Editor <span class="badge">Android companion</span></h1><div class="sub">Responsive SQL workspace · session-only credentials</div></div></div><div id="connectionBadge" class="badge">Not connected</div></div></header>
<main class="wrap">
<section id="pairPanel" class="panel"><h2>Unlock and pair with desktop</h2><p class="muted">Enter the same MySQL Editor master password you set on Windows and the temporary code shown in Tools → Android / Mobile Companion. The Windows desktop rejects a wrong password. Compare the SHA-256 certificate fingerprint before connecting and keep both devices on the same trusted private network.</p><div class="field"><label for="masterPassword">MySQL Editor master password</label><div class="secret-control"><input id="masterPassword" type="password" autocomplete="current-password" aria-describedby="masterPasswordHint"><button id="masterPasswordToggle" type="button" aria-label="Show master password" aria-pressed="false">Show</button></div><span id="masterPasswordHint" class="hint">This must match the password configured on the Windows desktop. It is checked over HTTPS and is not saved on Android.</span></div><div class="field" style="margin-top:12px"><label for="pairCode">Temporary pairing code</label><input id="pairCode" inputmode="numeric" pattern="[0-9]{10}" maxlength="10" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="10-digit code from desktop"></div><div class="actions"><button class="primary" id="pairBtn">Unlock and pair</button></div><div id="pairStatus" class="status" style="margin-top:12px">Both the master password and pairing code are required.</div></section>
<section id="connectionPanel" class="panel connection hidden"><div class="rowhead"><h2>MySQL connection</h2><button id="disconnectBtn" class="danger">Disconnect</button></div><div class="grid"><div class="field"><label for="host">Host (as seen by desktop)</label><input id="host" value="localhost" autocomplete="off"></div><div class="field"><label for="port">Port</label><input id="port" value="3306" inputmode="numeric"></div><div class="field"><label for="user">Username</label><input id="user" autocomplete="username"></div><div class="field"><label for="password">Password (not saved)</label><div class="secret-control"><input id="password" type="password" autocomplete="current-password" aria-describedby="passwordHint"><button id="passwordToggle" type="button" aria-label="Show password" aria-pressed="false">Show</button></div><span id="passwordHint" class="hint">Hidden by default and cleared after a successful connection.</span></div><div class="field wide"><label><input id="tlsVerify" type="checkbox" checked style="width:auto;margin-right:8px"> Require verified TLS to MySQL (recommended)</label><span class="hint">The MySQL server must present a certificate trusted by the desktop system or the CA file below.</span></div><div class="field wide"><label for="tlsCa">MySQL CA certificate path on desktop (optional)</label><input id="tlsCa" autocomplete="off" spellcheck="false" placeholder="C:\\certs\\mysql-ca.pem"><span class="hint">This path is read on the desktop computer, not on the phone.</span></div><div class="field wide"><label for="database">Database (optional)</label><input id="database" autocomplete="off"></div><div class="field wide"><label><input id="autocommit" type="checkbox" checked style="width:auto;margin-right:8px"> Auto-commit each statement</label></div></div><div class="actions"><button class="primary" id="connectBtn">Connect to MySQL</button></div><div class="hint">The desktop computer connects to MySQL. For a local database on that computer, use localhost.</div><div id="dbStatus" class="status" style="margin-top:10px">Not connected</div></section>
<section id="editorPanel" class="panel editor hidden"><div class="rowhead"><h2>SQL editor</h2><span class="hint">Ctrl/⌘ + Enter to run</span></div><textarea id="sql" autocapitalize="off" autocomplete="off" spellcheck="false" aria-label="SQL editor" placeholder="SELECT VERSION();"></textarea><div class="actions"><button id="runBtn" class="primary" disabled>Run SQL</button><button id="clearBtn">Clear</button><button id="historyBackBtn" disabled>Previous</button><button id="historyForwardBtn" disabled>Next</button><span id="historyCount" class="hint">0/50 queries in memory</span><button id="commitBtn" disabled>Commit</button><button id="rollbackBtn" disabled>Rollback</button></div><div class="actions"><select id="templateSelect" aria-label="SQL template"><option value="">Quick SQL template…</option><option value="SELECT VERSION();">Server version</option><option value="SELECT DATABASE();">Current database</option><option value="SHOW DATABASES;">List databases</option><option value="SHOW TABLES;">List tables</option><option value="SELECT NOW();">Current server time</option></select><button id="insertTemplateBtn">Insert template</button></div><div class="actions"><button id="formatSqlBtn">Format SQL</button><button id="explainSqlBtn">Explain SELECT</button><button id="copySqlBtn">Copy SQL</button></div><div class="grid" style="margin-top:10px"><div class="field"><label for="snippetName">Saved SQL snippet name (this session only)</label><input id="snippetName" maxlength="80" placeholder="e.g. Recent orders" autocomplete="off"></div><div class="field"><label for="savedSnippetSelect">Saved snippets</label><select id="savedSnippetSelect"><option value="">No saved snippets</option></select></div></div><div class="actions"><button id="saveSnippetBtn">Save snippet</button><button id="insertSavedSnippetBtn">Insert saved snippet</button></div><div id="queryStatus" class="status" style="margin-top:12px">Ready.</div></section>
<section id="resultPanel" class="panel result hidden"><div class="rowhead"><h2>Result</h2><button id="exportBtn" disabled>Export complete CSV</button></div><div id="metrics" class="metrics"></div><div id="resultTable" class="table-wrap" role="region" aria-label="Query results" tabindex="0"><div class="muted" style="padding:12px">Run a query to see results.</div></div></section>
</main><footer>HTTPS is certificate-pinned between the app and desktop. Use a trusted private network; never expose this service to the public internet.</footer>
<script>
(()=>{'use strict';
const $=id=>document.getElementById(id);let sessionToken='';sessionStorage.removeItem('mysqlIdleMobileSession');let lastResult=false;let connected=false;let queryRunning=false;const queryHistory=[];const savedSnippets=new Map();let historyIndex=0;let historyDraft='';
function status(id,msg,kind=''){const el=$(id);el.textContent=msg;el.className='status'+(kind?' '+kind:'');}
function updateActionStates(){$('runBtn').disabled=!connected||queryRunning;$('commitBtn').disabled=!connected||queryRunning;$('rollbackBtn').disabled=!connected||queryRunning;$('connectBtn').disabled=queryRunning;$('exportBtn').disabled=!lastResult||queryRunning;}
function setConnectedState(value){connected=!!value;updateActionStates();}
function clearSession(){sessionToken='';sessionStorage.removeItem('mysqlIdleMobileSession');setConnectedState(false);lastResult=false;clearQueryHistory();savedSnippets.clear();updateSavedSnippetOptions();$('sql').value='';updateActionStates();showApp(false);}
function showApp(show){$('pairPanel').classList.toggle('hidden',show);$('connectionPanel').classList.toggle('hidden',!show);$('editorPanel').classList.toggle('hidden',!show);$('resultPanel').classList.toggle('hidden',!show);}
function updateHistoryControls(){const total=queryHistory.length;$('historyBackBtn').disabled=!total||historyIndex<=0;$('historyForwardBtn').disabled=!total||historyIndex>=total;$('historyCount').textContent=total+'/50 queries in memory';}
function rememberQuery(sql){if(queryHistory[queryHistory.length-1]!==sql){queryHistory.push(sql);if(queryHistory.length>50)queryHistory.shift();}historyIndex=queryHistory.length;historyDraft='';updateHistoryControls();}
function moveHistory(direction){if(!queryHistory.length)return;const input=$('sql');if(historyIndex===queryHistory.length)historyDraft=input.value;const next=Math.max(0,Math.min(queryHistory.length,historyIndex+direction));if(next===historyIndex)return;historyIndex=next;input.value=historyIndex===queryHistory.length?historyDraft:queryHistory[historyIndex];input.focus();input.setSelectionRange(input.value.length,input.value.length);updateHistoryControls();}
function clearQueryHistory(){queryHistory.length=0;historyIndex=0;historyDraft='';updateHistoryControls();}
function updateSavedSnippetOptions(){
 const select=$('savedSnippetSelect');
 if(!select)return;
 select.replaceChildren(new Option('Choose a saved snippet…',''));
 for(const name of savedSnippets.keys())select.add(new Option(name,name));
}
function splitSqlSegments(sql){
 const parts=[];let i=0,start=0,n=sql.length;
 const add=(kind,from,to)=>{if(to>from)parts.push({kind,text:sql.slice(from,to)})};
 while(i<n){
  const ch=sql[i];let opaqueEnd=-1;
  if(ch==="'"||ch==='"'||ch==='\`'){
   const quote=ch;let j=i+1;
   while(j<n){
    if(sql[j]==='\\'&&quote!=='\`'){j=Math.min(n,j+2);continue}
    if(sql[j]===quote){if(j+1<n&&sql[j+1]===quote){j+=2;continue}j++;break}
    j++;
   }
   opaqueEnd=j;
  }else if(ch==='#'||(sql.startsWith('--',i)&&(i+2===n||/\s/.test(sql[i+2])))){
   const newline=sql.indexOf('\n',i);opaqueEnd=newline<0?n:newline+1;
  }else if(sql.startsWith('/*',i)){
   const end=sql.indexOf('*/',i+2);opaqueEnd=end<0?n:end+2;
  }
  if(opaqueEnd>=0){add('code',start,i);add('opaque',i,opaqueEnd);i=opaqueEnd;start=i}
  else i++;
 }
 add('code',start,n);
 return parts;
}
const SQL_KEYWORDS="ALL ALTER AND AS ASC BETWEEN BY CASE CAST COLLATE CROSS CURRENT_DATE CURRENT_TIME CURRENT_TIMESTAMP DATABASE DATABASES DESC DISTINCT ELSE END EXISTS FALSE FROM FULL GROUP HAVING IN INNER INTERSECT IS JOIN LEFT LIKE LIMIT NATURAL NOT NULL OFFSET ON OR ORDER OUTER RIGHT SELECT SET SHOW TABLES THEN TRUE UNION UNKNOWN USE USING VALUES WHEN WHERE WITH".split(/\s+/);
function formatSqlCode(code){
 code=code.replace(/\s+/g,' ');
 const pattern=new RegExp('\\b(?:'+SQL_KEYWORDS.slice().sort((a,b)=>b.length-a.length).join('|')+')\\b','gi');
 code=code.replace(pattern,word=>word.toUpperCase());
 code=code.replace(/[ \t]+(?=(?:FROM|WHERE|GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT|UNION(?:\s+ALL)?|LEFT(?:\s+OUTER)?\s+JOIN|RIGHT(?:\s+OUTER)?\s+JOIN|INNER\s+JOIN|CROSS\s+JOIN|JOIN)\b)/gi,'\n');
 code=code.replace(/[ \t]*(<=|>=|<>|!=|=|<|>)[ \t]*/g,' $1 ');
 code=code.replace(/,[ \t]*/g,', ');
 code=code.replace(/[ \t]+\n/g,'\n').replace(/\n[ \t]+/g,'\n').replace(/\n{2,}/g,'\n');
 return code;
}
function formatSql(sql){
 if(!sql.trim())return sql;
 return splitSqlSegments(sql).map(p=>p.kind==='code'?formatSqlCode(p.text):p.text).join('').trim();
}
function buildExplainSql(sql){
 if(!sql.trim())throw new Error('Enter a SELECT statement first.');
 const code=splitSqlSegments(sql).map(p=>p.kind==='code'?p.text:' ').join('').trim();
 if(!/^SELECT\b/i.test(code))throw new Error('Explain Plan only accepts a single SELECT statement.');
 const withoutFinal=code.endsWith(';')?code.slice(0,-1).trimEnd():code;
 if(withoutFinal.includes(';'))throw new Error('Explain Plan accepts one statement at a time.');
 const parts=splitSqlSegments(sql.trim());let inserted=false;let out='';
 for(const part of parts){
  if(!inserted&&part.kind==='code'){
   const match=/\S/.exec(part.text);
   if(match){out+=part.text.slice(0,match.index)+'EXPLAIN '+part.text.slice(match.index);inserted=true;continue}
  }
  out+=part.text;
 }
 if(!inserted)throw new Error('Could not locate the SELECT statement.');
 return out;
}
async function copyText(value){
 try{
  if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(value);return}
 }catch(_){}
 const temporary=document.createElement('textarea');temporary.value=value;temporary.setAttribute('readonly','');temporary.style.position='fixed';temporary.style.opacity='0';document.body.append(temporary);temporary.select();
 const copied=document.execCommand('copy');temporary.remove();
 if(!copied)throw new Error('Clipboard access is unavailable in this WebView.');
}
async function api(path,data,method='POST'){const headers={};if(method!=='GET')headers['Content-Type']='application/json';if(sessionToken)headers.Authorization='Bearer '+sessionToken;const response=await fetch(path,{method,headers,body:method==='GET'?undefined:JSON.stringify(data||{})});let json={};try{json=await response.json()}catch{}if(response.status===401){const message=json.error||'Pairing expired. Pair again.';clearSession();throw new Error(message)}if(!response.ok||json.ok===false)throw Object.assign(new Error(json.error||('Request failed ('+response.status+')')),json);return json;}
$('passwordToggle').onclick=()=>{const reveal=$('password').type==='password';$('password').type=reveal?'text':'password';$('passwordToggle').textContent=reveal?'Hide':'Show';$('passwordToggle').setAttribute('aria-pressed',String(reveal));$('passwordToggle').setAttribute('aria-label',reveal?'Hide password':'Show password');};
$('masterPasswordToggle').onclick=()=>{const reveal=$('masterPassword').type==='password';$('masterPassword').type=reveal?'text':'password';$('masterPasswordToggle').textContent=reveal?'Hide':'Show';$('masterPasswordToggle').setAttribute('aria-pressed',String(reveal));$('masterPasswordToggle').setAttribute('aria-label',reveal?'Hide master password':'Show master password');};
$('pairBtn').onclick=async()=>{const btn=$('pairBtn');btn.disabled=true;try{const r=await fetch('/api/pair',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:$('pairCode').value.trim(),masterPassword:$('masterPassword').value})});const j=await r.json();if(!r.ok||!j.ok)throw new Error(j.error||'Pairing failed');sessionToken=j.token;$('masterPassword').value='';$('pairCode').value='';showApp(true);status('dbStatus','Not connected');$('connectionBadge').textContent='Unlocked · not connected';status('pairStatus','Master password verified. Device paired.','good');}catch(e){$('masterPassword').value='';status('pairStatus',e.message,'bad')}finally{btn.disabled=false}};
$('connectBtn').onclick=async()=>{const b=$('connectBtn');b.disabled=true;status('dbStatus','Connecting…');try{const r=await api('/api/connect',{host:$('host').value.trim(),port:$('port').value.trim(),user:$('user').value,password:$('password').value,database:$('database').value.trim(),autocommit:$('autocommit').checked,tlsVerify:$('tlsVerify').checked,sslCa:$('tlsCa').value.trim()});setConnectedState(true);lastResult=false;$('resultPanel').classList.add('hidden');$('resultTable').textContent='Run a query to see results.';status('dbStatus','Connected to '+r.serverVersion,'good');$('connectionBadge').textContent='Connected · '+(r.database||'no database');$('password').value='';updateActionStates();}catch(e){status('dbStatus',e.message+(connected?' The previous connection is still active.':''),'bad');}finally{b.disabled=false;updateActionStates()}};
async function governedQuery(sql){try{return await api('/api/query',{sql})}catch(e){if(!e.approval_required||!e.approvalToken)throw e;const promptText='Feature Governance flagged '+(e.category||'high-impact')+' SQL ('+(e.risk||'high')+' risk).\n\n'+(e.reason||'This statement may cause significant changes.')+'\n\nApprove this exact statement once?';if(!window.confirm(promptText))throw new Error('Cancelled by Feature Governance.');return api('/api/query',{sql,approvalToken:e.approvalToken})}}
$('runBtn').onclick=async()=>{const sql=$('sql').value.trim();if(!sql){status('queryStatus','Enter a SQL statement first.');return}rememberQuery(sql);queryRunning=true;updateActionStates();lastResult=false;updateActionStates();status('queryStatus','Running query…');$('metrics').replaceChildren();$('resultTable').textContent='Query running…';$('resultPanel').classList.remove('hidden');try{const r=await governedQuery(sql);status('queryStatus',r.message||'Query completed.','good');if(r.database!==undefined)$('connectionBadge').textContent='Connected · '+(r.database||'no database');$('metrics').replaceChildren();[['Rows',r.rowCount],['Time',r.elapsed.toFixed(3)+' s'],['Mode',r.hasResult?'result set':'statement']].forEach(([k,v])=>{const span=document.createElement('span');const strong=document.createElement('strong');strong.textContent=k+': ';span.append(strong,document.createTextNode(String(v)));$('metrics').append(span)});renderTable(r.columns||[],r.preview||[]);lastResult=!!r.hasResult;$('resultPanel').classList.remove('hidden');if(r.truncated||r.truncatedColumns){const notes=[];if(r.truncated)notes.push(`first ${r.preview.length} rows of ${r.rowCount}`);if(r.truncatedColumns)notes.push(`first ${r.columns.length} of ${r.totalColumns} columns`);status('queryStatus',`Preview limited to ${notes.join(' and ')}. Export contains the complete result.`,'good');}}catch(e){status('queryStatus',e.message,'bad')}finally{queryRunning=false;updateActionStates()}};
function renderTable(columns,rows){const wrap=$('resultTable');wrap.replaceChildren();if(!columns.length){wrap.textContent='Statement completed without a result set.';return}const table=document.createElement('table'),thead=document.createElement('thead'),hr=document.createElement('tr');columns.forEach(c=>{const th=document.createElement('th');th.scope='col';th.textContent=c;hr.append(th)});thead.append(hr);table.append(thead);const body=document.createElement('tbody');rows.forEach(row=>{const tr=document.createElement('tr');row.forEach(v=>{const td=document.createElement('td');if(v===null){td.textContent='NULL';td.className='null'}else td.textContent=String(v);tr.append(td)});body.append(tr)});table.append(body);wrap.append(table);if(!rows.length){const p=document.createElement('div');p.className='muted';p.style.padding='12px';p.textContent='Empty result set.';wrap.append(p)}}
$('exportBtn').onclick=async()=>{try{const response=await fetch('/api/export',{headers:{Authorization:'Bearer '+sessionToken}});if(response.status===401){clearSession();throw new Error('Pairing expired. Pair again.')}if(!response.ok){let message='Export unavailable ('+response.status+').';try{const body=await response.json();message=body.error||message}catch{}throw new Error(message)}const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='mysql_idle_result.csv';document.body.append(a);a.click();a.remove();window.setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){status('queryStatus',e.message,'bad')}};
async function txn(action){try{const r=await api('/api/transaction',{action});status('queryStatus',r.message,'good')}catch(e){status('queryStatus',e.message,'bad')}}
$('commitBtn').onclick=()=>txn('commit');$('rollbackBtn').onclick=()=>txn('rollback');
$('disconnectBtn').onclick=async()=>{try{await api('/api/disconnect',{});setConnectedState(false);status('dbStatus','Disconnected');$('connectionBadge').textContent='Paired · not connected';lastResult=false;clearQueryHistory();$('sql').value='';updateActionStates();$('resultPanel').classList.add('hidden')}catch(e){status('dbStatus',e.message,'bad')}};
$('clearBtn').onclick=()=>{$('sql').value='';historyIndex=queryHistory.length;historyDraft='';updateHistoryControls();$('sql').focus()};$('historyBackBtn').onclick=()=>moveHistory(-1);$('historyForwardBtn').onclick=()=>moveHistory(1);$('insertTemplateBtn').onclick=()=>{const value=$('templateSelect').value;if(!value){status('queryStatus','Choose a template first.');return}const input=$('sql');input.value=(input.value.trim()?input.value+'\n':'')+value;input.focus();input.setSelectionRange(input.value.length,input.value.length);status('queryStatus','Template inserted. Review it before running.','good')};
$('formatSqlBtn').onclick=()=>{const input=$('sql');if(!input.value.trim()){status('queryStatus','Enter SQL before formatting.');return}input.value=formatSql(input.value);input.focus();status('queryStatus','SQL formatted locally. Review it before execution.','good')};
$('explainSqlBtn').onclick=()=>{try{$('sql').value=buildExplainSql($('sql').value);$('sql').focus();status('queryStatus','EXPLAIN inserted. Review the statement, then tap Run SQL.','good')}catch(e){status('queryStatus',e.message,'bad')}};
$('copySqlBtn').onclick=async()=>{const sql=$('sql').value;if(!sql.trim()){status('queryStatus','There is no SQL to copy.');return}try{await copyText(sql);status('queryStatus','SQL copied to clipboard.','good')}catch(e){status('queryStatus',e.message,'bad')}};
$('saveSnippetBtn').onclick=()=>{const name=$('snippetName').value.trim();const sql=$('sql').value;if(!name||name.length>80){status('queryStatus','Choose a snippet name from 1 to 80 characters.','bad');return}if(!sql.trim()){status('queryStatus','Enter SQL before saving a snippet.','bad');return}if(sql.length>65536){status('queryStatus','Snippets are limited to 64 KiB each.','bad');return}if(!savedSnippets.has(name)&&savedSnippets.size>=20){status('queryStatus','This session already has 20 saved snippets.','bad');return}savedSnippets.set(name,sql);updateSavedSnippetOptions();$('savedSnippetSelect').value=name;status('queryStatus','Snippet saved in memory for this mobile session only.','good')};
$('insertSavedSnippetBtn').onclick=()=>{const name=$('savedSnippetSelect').value;const sql=savedSnippets.get(name);if(!sql){status('queryStatus','Choose a saved snippet first.');return}$('sql').value=sql;$('sql').focus();$('sql').setSelectionRange(sql.length,sql.length);status('queryStatus','Snippet inserted. Review it before running.','good')};
$('sql').addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();$('runBtn').click()}});
updateHistoryControls();if(sessionToken){api('/api/state',{},'GET').then(r=>{showApp(true);setConnectedState(!!r.connected);if(r.connected){$('connectionBadge').textContent='Connected · '+(r.database||'no database');status('dbStatus','Connected to '+r.serverVersion,'good')}else{$('connectionBadge').textContent='Paired · not connected'}updateActionStates()}).catch(()=>clearSession())}else{showApp(false);updateActionStates()}
})();</script></body></html>'''


def _json_default(value):
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", "replace")
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat(sep=" ") if isinstance(value, _dt.datetime) else value.isoformat()
    return str(value)


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", "replace")
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return _json_default(value)
    return value


def _preview_value(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = _json_default(value)
    if len(text) > MAX_PREVIEW_CELL_CHARS:
        return text[:MAX_PREVIEW_CELL_CHARS - 3] + "..."
    return text


def _local_ip():
    """Choose a private LAN IPv4 address; never advertise or bind a public IP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect selects a route; it does not send application data.
        sock.connect(("192.0.2.1", 9))
        candidate = ipaddress.ip_address(sock.getsockname()[0])
        if candidate.version == 4 and candidate.is_private and not candidate.is_loopback and not candidate.is_link_local:
            return str(candidate)
    except (OSError, ValueError):
        pass
    finally:
        sock.close()
    return "127.0.0.1"


def _create_tls_identity(directory, bind_host):
    """Create a short-lived self-signed TLS certificate whose pin is shown to the user."""
    now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "MySQL Editor Mobile Companion"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MySQL Editor"),
    ])
    san_names = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    bind_ip = ipaddress.ip_address(bind_host)
    if bind_ip not in [entry.value for entry in san_names if isinstance(entry, x509.IPAddress)]:
        san_names.append(x509.IPAddress(bind_ip))
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName(san_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = Path(directory) / "mobile-companion-cert.pem"
    key_path = Path(directory) / "mobile-companion-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    if os.name != "nt":
        os.chmod(cert_path, 0o600)
        os.chmod(key_path, 0o600)
    fingerprint = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest().upper()
    fingerprint = ":".join(fingerprint[i:i + 2] for i in range(0, len(fingerprint), 2))
    return cert_path, key_path, fingerprint


class _BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Bound worker threads so a burst of clients cannot exhaust desktop resources."""
    daemon_threads = True
    block_on_close = False
    request_queue_size = 16

    def __init__(self, server_address, request_handler):
        self._request_slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)
        self.tls_context = None
        super().__init__(server_address, request_handler)

    def process_request(self, request, client_address):
        # Acquire capacity before TLS negotiation. Over-capacity clients are
        # closed immediately so handshakes cannot accumulate on the accept loop.
        if not self._request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        secure_request = None
        try:
            if self.tls_context is None:
                raise RuntimeError("TLS context is not configured.")
            secure_request = self.tls_context.wrap_socket(
                request, server_side=True, do_handshake_on_connect=False
            )
            secure_request.settimeout(15)
            super().process_request(secure_request, client_address)
        except Exception:
            try:
                self.shutdown_request(secure_request or request)
            except OSError:
                pass
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            try:
                request.do_handshake()
            except (ssl.SSLError, OSError):
                self.shutdown_request(request)
                return
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


class _MobileSession:
    def __init__(self, client_ip=None):
        self.client_ip = client_ip
        self.created = time.monotonic()
        self.last_active = self.created
        self.lock = threading.RLock()
        self.conn = None
        self.current_db = None
        self.server_version = ""
        self.last_result_path = None
        self.last_result_columns = None
        # Challenges are random, session-bound, single-use, and short-lived.
        self.pending_approvals = {}

    def touch(self):
        self.last_active = time.monotonic()

    def close(self):
        with self.lock:
            if self.conn is not None:
                try:
                    self.conn.close()
                except Exception:
                    pass
            self.conn = None
            self.current_db = None
            result_path, self.last_result_path = self.last_result_path, None
            self.last_result_columns = None
            self.pending_approvals.clear()
            if result_path:
                try:
                    os.unlink(result_path)
                except OSError:
                    pass


class MobileCompanionServer:
    """Start/stop the mobile companion. Public-LAN access is never automatic."""

    def __init__(self, port=8765, bind_host=None, governor=None, password_record=None):
        if not is_password_record(password_record):
            raise ValueError("Set a master password in the Windows MySQL Editor app before enabling the Android companion.")
        self.password_record = dict(password_record)
        if bind_host is None:
            bind_host = _local_ip()
            if bind_host == "127.0.0.1":
                raise RuntimeError("No private LAN IPv4 address was found. Connect to a trusted private network, then enable the mobile companion.")
        try:
            bind_address = ipaddress.ip_address(str(bind_host))
        except ValueError as exc:
            raise ValueError("The mobile companion must bind to a private numeric IPv4 address.") from exc
        if bind_address.version != 4 or bind_address.is_unspecified or not (bind_address.is_private or bind_address.is_loopback):
            raise ValueError("For safety, the mobile companion will not bind to a wildcard or public IP address.")
        self.pairing_code = f"{secrets.randbelow(10**10):010d}"
        self.sessions = {}
        self.sessions_lock = threading.RLock()
        self.attempts = {}
        self.attempts_lock = threading.Lock()
        self.temp_dir = tempfile.TemporaryDirectory(prefix="mysql_idle_mobile_")
        try:
            (Path(self.temp_dir.name) / ".owner_pid").write_text(str(os.getpid()), encoding="ascii")
        except OSError:
            pass
        self._running = False
        self._serve_thread = None
        self.port_requested = int(port)
        self.bind_host = str(bind_host)
        self.governor = governor or FeatureGovernor()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "MySQLIDLEMobile/1"
            sys_version = ""

            def setup(self):
                super().setup()
                self.connection.settimeout(15)

            def log_message(self, fmt, *args):
                # Never write client IPs, pairing data, SQL, or request metadata to console.
                return

            def _headers(self, content_type="application/json; charset=utf-8", length=None, script_nonce=None):
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                self.send_header("Cross-Origin-Opener-Policy", "same-origin")
                self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), usb=()")
                script_policy = f"'nonce-{script_nonce}'" if script_nonce else "'none'"
                csp = (
                    "default-src 'self'; "
                    f"script-src {script_policy}; "
                    "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
                    "object-src 'none'; frame-src 'none'; worker-src 'none'; "
                    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
                )
                self.send_header("Content-Security-Policy", csp)
                if length is not None:
                    self.send_header("Content-Length", str(length))

            def _send_bytes(self, status, data, content_type="application/json; charset=utf-8", extra_headers=None, script_nonce=None):
                self.send_response(status)
                self._headers(content_type, len(data), script_nonce=script_nonce)
                for name, value in (extra_headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _json(self, status, obj):
                body = json.dumps(obj, ensure_ascii=False, default=_json_default, separators=(",", ":")).encode("utf-8")
                self._send_bytes(status, body)

            def _host_allowed(self):
                host_header = self.headers.get("Host", "")
                try:
                    parsed = urlparse("//" + host_header)
                    host = (parsed.hostname or "").lower()
                    port = parsed.port
                except ValueError:
                    return False
                if (
                    not host
                    or parsed.username is not None
                    or parsed.password is not None
                    or parsed.path
                    or parsed.query
                    or parsed.fragment
                ):
                    return False
                return port == owner.httpd.server_address[1] and host in owner.allowed_hosts

            def _origin_allowed(self):
                origin = self.headers.get("Origin")
                if not origin:
                    return True
                try:
                    parsed = urlparse(origin)
                    host = (parsed.hostname or "").lower()
                    port = parsed.port
                except ValueError:
                    return False
                local_port = owner.httpd.server_address[1]
                return (
                    parsed.scheme == "https"
                    and parsed.username is None
                    and parsed.password is None
                    and parsed.path in ("", "/")
                    and not parsed.query
                    and not parsed.fragment
                    and port == local_port
                    and host in owner.allowed_hosts
                )

            def _read_json(self):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError as exc:
                    raise ValueError("Invalid Content-Length.") from exc
                if length < 0:
                    raise ValueError("Invalid Content-Length.")
                if length > MAX_BODY_BYTES:
                    raise RequestBodyTooLarge(
                        f"Request body exceeds the {MAX_BODY_BYTES // 1024} KiB limit."
                    )
                raw = self.rfile.read(length) if length else b"{}"
                obj = json.loads(raw.decode("utf-8"))
                if not isinstance(obj, dict):
                    raise ValueError("Request must be a JSON object.")
                return obj

            def _session(self, required=True):
                auth = self.headers.get("Authorization", "")
                token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
                if not token:
                    if required:
                        raise PermissionError("Pair this device first.")
                    return None
                with owner.sessions_lock:
                    session = owner.sessions.get(token)
                    if session and time.monotonic() - session.last_active > IDLE_TIMEOUT_SECONDS:
                        owner.sessions.pop(token, None)
                        session.close()
                        session = None
                    if session:
                        session.touch()
                    elif required:
                        raise PermissionError("Mobile session expired. Pair this device again.")
                    return session

            def do_GET(self):
                if not self._host_allowed():
                    self._json(403, {"ok": False, "error": "Unrecognized Host header."})
                    return
                path = urlparse(self.path).path
                if path == "/":
                    nonce = secrets.token_urlsafe(18)
                    html = MOBILE_HTML.replace("<script>", f'<script nonce="{nonce}">', 1)
                    body = html.encode("utf-8")
                    self._send_bytes(200, body, "text/html; charset=utf-8", script_nonce=nonce)
                elif path == "/brand/mysqlidle-logo.png":
                    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
                    logo_candidates = (
                        bundle_root / "assets" / "mysqlidle-logo.png",
                        Path(__file__).resolve().parent / "assets" / "mysqlidle-logo.png",
                    )
                    logo_path = next((candidate for candidate in logo_candidates if candidate.is_file()), None)
                    if logo_path is None:
                        self._json(404, {"ok": False, "error": "Brand logo is unavailable."})
                        return
                    try:
                        self._send_bytes(200, logo_path.read_bytes(), "image/png")
                    except OSError:
                        self._json(404, {"ok": False, "error": "Brand logo is unavailable."})
                elif path == "/api/state":
                    try:
                        s = self._session()
                        with s.lock:
                            self._json(200, {"ok": True, "connected": s.conn is not None,
                                "database": s.current_db or "", "serverVersion": s.server_version})
                    except PermissionError as exc:
                        self._json(401, {"ok": False, "error": str(exc)})
                elif path == "/api/export":
                    try:
                        s = self._session()
                        with s.lock:
                            p = s.last_result_path
                            if not p or not os.path.isfile(p):
                                self._json(404, {"ok": False, "error": "No CSV result is available."})
                                return
                            self.send_response(200)
                            self._headers("text/csv; charset=utf-8", os.path.getsize(p))
                            self.send_header("Content-Disposition", 'attachment; filename="mysql_idle_result.csv"')
                            self.end_headers()
                            with open(p, "rb") as fh:
                                while True:
                                    chunk = fh.read(128 * 1024)
                                    if not chunk:
                                        break
                                    self.wfile.write(chunk)
                    except PermissionError as exc:
                        self._json(401, {"ok": False, "error": str(exc)})
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                else:
                    self._json(404, {"ok": False, "error": "Not found."})

            def do_POST(self):
                if not self._host_allowed() or not self._origin_allowed():
                    self._json(403, {"ok": False, "error": "Request origin rejected."})
                    return
                path = urlparse(self.path).path
                content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type != "application/json":
                    self._json(415, {"ok": False, "error": "Content-Type must be application/json."})
                    return
                try:
                    data = self._read_json()
                except RequestBodyTooLarge as exc:
                    self._json(413, {"ok": False, "error": str(exc)})
                    return
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    self._json(400, {"ok": False, "error": str(exc) or "Invalid JSON."})
                    return
                if path == "/api/pair":
                    self._pair(data)
                    return
                try:
                    session = self._session()
                except PermissionError as exc:
                    self._json(401, {"ok": False, "error": str(exc)})
                    return
                if path == "/api/connect":
                    self._connect(session, data)
                elif path == "/api/query":
                    self._query(session, data)
                elif path == "/api/transaction":
                    self._transaction(session, data)
                elif path == "/api/disconnect":
                    session.close()
                    self._json(200, {"ok": True, "message": "Disconnected."})
                else:
                    self._json(404, {"ok": False, "error": "Not found."})

            def _pair(self, data):
                if not owner._running:
                    self._json(503, {"ok": False, "error": "Mobile companion is stopped."})
                    return
                ip = self.client_address[0]
                now = time.monotonic()
                with owner.attempts_lock:
                    if ip not in owner.attempts and len(owner.attempts) >= 256:
                        owner.attempts.pop(next(iter(owner.attempts)))
                    failures, blocked_until = owner.attempts.get(ip, (0, 0.0))
                    if now < blocked_until:
                        self._json(429, {"ok": False, "error": "Too many pairing attempts. Try again in one minute."})
                        return
                code = str(data.get("code", ""))
                master_password = data.get("masterPassword", "")
                code_valid = secrets.compare_digest(code, owner.pairing_code)
                password_valid = verify_password(master_password, owner.password_record)
                if not (code_valid and password_valid):
                    with owner.attempts_lock:
                        failures, _ = owner.attempts.get(ip, (0, 0.0))
                        failures += 1
                        owner.attempts[ip] = (failures, now + PAIR_LOCKOUT_SECONDS if failures >= MAX_PAIR_FAILURES else 0.0)
                    self._json(401, {"ok": False, "error": "Invalid master password or pairing code."})
                    return
                with owner.sessions_lock:
                    owner._purge_expired_sessions()
                    # A reload on the same phone must re-authenticate. Retire that
                    # phone's previous in-memory token so repeated logins do not fill
                    # the bounded session table.
                    for old_token, old_session in list(owner.sessions.items()):
                        if old_session.client_ip == ip:
                            owner.sessions.pop(old_token, None)
                            old_session.close()
                    if len(owner.sessions) >= MAX_SESSIONS:
                        self._json(429, {"ok": False, "error": "Maximum paired devices reached. Restart the companion to reset pairing."})
                        return
                    token = secrets.token_urlsafe(32)
                    owner.sessions[token] = _MobileSession(client_ip=ip)
                with owner.attempts_lock:
                    owner.attempts.pop(ip, None)
                self._json(200, {"ok": True, "token": token})

            def _connect(self, session, data):
                host = str(data.get("host", "localhost")).strip()[:255] or "localhost"
                user = str(data.get("user", "")).strip()[:128]
                password = str(data.get("password", ""))
                database = str(data.get("database", "")).strip()[:255] or None
                try:
                    port = int(data.get("port", 3306))
                    if not 1 <= port <= 65535:
                        raise ValueError
                    if not user:
                        raise ValueError("Username is required.")
                except ValueError as exc:
                    self._json(400, {"ok": False, "error": str(exc) if str(exc) else "Port must be 1–65535."})
                    return
                ssl_ca = str(data.get("sslCa", "")).strip()[:1024]
                tls_verify = bool(data.get("tlsVerify", True))
                if ssl_ca and not os.path.isfile(ssl_ca):
                    self._json(400, {"ok": False, "error": "The MySQL CA certificate file was not found on the desktop."})
                    return
                connection_options = {
                    "host": host, "port": port, "user": user, "password": password,
                    "database": database, "charset": "utf8mb4", "autocommit": bool(data.get("autocommit", True)),
                    "connect_timeout": 8, "read_timeout": 90, "write_timeout": 15,
                }
                if tls_verify:
                    connection_options.update(ssl_verify_cert=True, ssl_verify_identity=True)
                if ssl_ca:
                    connection_options["ssl_ca"] = ssl_ca
                try:
                    conn = pymysql.connect(**connection_options)
                    version = str(conn.get_server_info())
                except Exception as exc:
                    self._json(400, {"ok": False, "error": _database_error(exc)})
                    return
                with session.lock:
                    old = session.conn
                    old_result = session.last_result_path
                    session.conn = conn
                    session.current_db = database
                    session.server_version = version
                    session.last_result_path = None
                    session.last_result_columns = None
                    if old_result:
                        try:
                            os.unlink(old_result)
                        except OSError:
                            pass
                    if old is not None:
                        try:
                            old.close()
                        except Exception:
                            pass
                self._json(200, {"ok": True, "serverVersion": version, "database": database or ""})

            def _query(self, session, data):
                sql = data.get("sql")
                if not isinstance(sql, str) or not sql.strip():
                    self._json(400, {"ok": False, "error": "Enter a SQL statement."})
                    return
                if len(sql.encode("utf-8")) > MAX_SQL_BYTES:
                    self._json(413, {"ok": False, "error": "SQL statement exceeds the 256 KiB limit."})
                    return

                # Govern before touching the DB cursor. A challenge is tied to this
                # session and exact SQL digest, expires quickly, and can be used once.
                assessment = owner.governor.inspect_sql(sql)
                if assessment["decision"] == "block":
                    owner.governor.record_decision(sql, "block", str(assessment["reason"]),
                                                   str(assessment["category"]), str(assessment["risk"]))
                    self._json(403, {"ok": False, "error": str(assessment["reason"]),
                                     "governance_blocked": True, "risk": assessment["risk"]})
                    return

                approved = False
                if assessment["decision"] == "confirm":
                    approval_token = str(data.get("approvalToken", "")).strip()[:128]
                    digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
                    now = time.monotonic()
                    challenge_token = None
                    with session.lock:
                        session.pending_approvals = {
                            token: item for token, item in session.pending_approvals.items()
                            if item[1] > now
                        }
                        if not approval_token:
                            # Bound challenge memory even for a noisy paired client.
                            while len(session.pending_approvals) >= 16:
                                session.pending_approvals.pop(next(iter(session.pending_approvals)))
                            challenge_token = secrets.token_urlsafe(32)
                            session.pending_approvals[challenge_token] = (
                                digest, now + 45.0
                            )
                        else:
                            issued = session.pending_approvals.pop(approval_token, None)
                            approved = bool(
                                issued and issued[1] > now and
                                secrets.compare_digest(issued[0], digest)
                            )
                    if challenge_token:
                        reason = str(assessment["reason"])
                        owner.governor.record_decision(
                            sql, "confirmation_required", reason,
                            str(assessment["category"]), str(assessment["risk"]),
                        )
                        self._json(409, {
                            "ok": False,
                            "error": "High-impact SQL requires explicit approval.",
                            "approval_required": True,
                            "approvalToken": challenge_token,
                            "reason": reason,
                            "category": assessment["category"],
                            "risk": assessment["risk"],
                        })
                        return
                    if not approved:
                        owner.governor.record_decision(
                            sql, "approval_rejected", "Invalid, expired, or mismatched one-time approval.",
                            str(assessment["category"]), str(assessment["risk"]),
                        )
                        self._json(403, {
                            "ok": False,
                            "error": "Approval expired or did not match this exact statement. Run it again to request a fresh approval.",
                            "governance_blocked": True,
                        })
                        return

                policy = owner.governor.check_sql(sql, externally_approved=approved)
                if policy["decision"] != "allow":
                    self._json(403, {"ok": False, "error": str(policy["reason"]),
                                     "governance_blocked": True, "risk": policy["risk"]})
                    return

                started = time.perf_counter()
                with session.lock:
                    if session.conn is None:
                        self._json(400, {"ok": False, "error": "Connect to MySQL first."})
                        return
                    previous = session.last_result_path
                    session.last_result_path = None
                    session.last_result_columns = None
                    if previous:
                        try:
                            os.unlink(previous)
                        except OSError:
                            pass
                    try:
                        with session.conn.cursor(pymysql.cursors.SSCursor) as cur:
                            cur.execute(sql)
                            if cur.description:
                                all_columns = [str(item[0]) for item in cur.description]
                                columns = all_columns[:MAX_PREVIEW_COLUMNS]
                                fd, path = tempfile.mkstemp(prefix="mobile_result_", suffix=".csv", dir=owner.temp_dir.name)
                                os.close(fd)
                                count = 0
                                preview = []
                                try:
                                    try:
                                        csv.field_size_limit(2**31 - 1)
                                    except OverflowError:
                                        csv.field_size_limit(2**30)
                                    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                                        writer = csv.writer(fh)
                                        writer.writerow(all_columns)
                                        while True:
                                            batch = cur.fetchmany(FETCH_BATCH_SIZE)
                                            if not batch:
                                                break
                                            for row in batch:
                                                writer.writerow([_csv_value(v) for v in row])
                                                if count < MAX_PREVIEW_ROWS:
                                                    preview.append([_preview_value(v) for v in row[:MAX_PREVIEW_COLUMNS]])
                                                count += 1
                                            if os.path.getsize(path) > MAX_RESULT_BYTES:
                                                raise ResultTooLarge
                                except Exception:
                                    try:
                                        os.unlink(path)
                                    except OSError:
                                        pass
                                    raise
                                session.last_result_path = path
                                session.last_result_columns = columns
                                elapsed = time.perf_counter() - started
                                self._json(200, {"ok": True, "hasResult": True, "columns": columns,
                                    "totalColumns": len(all_columns), "truncatedColumns": len(all_columns) > len(columns),
                                    "preview": preview, "rowCount": count, "database": session.current_db or "",
                                    "truncated": count > len(preview),
                                    "elapsed": elapsed, "message": f"{count} row(s) in {elapsed:.3f} sec."})
                            else:
                                affected = cur.rowcount
                                stripped = sql.strip().rstrip(";").strip()
                                if stripped.upper().startswith("USE "):
                                    # Ask the active connection for the actual current database.
                                    with session.conn.cursor() as meta:
                                        meta.execute("SELECT DATABASE()")
                                        value = meta.fetchone()
                                        session.current_db = value[0] if value else None
                                elapsed = time.perf_counter() - started
                                self._json(200, {"ok": True, "hasResult": False, "columns": [], "preview": [],
                                    "rowCount": max(0, affected), "database": session.current_db or "",
                                    "truncated": False, "elapsed": elapsed,
                                    "message": f"Statement completed; {affected} row(s) affected in {elapsed:.3f} sec."})
                    except ResultTooLarge:
                        self._json(413, {
                            "ok": False,
                            "error": f"Result exceeds the {MAX_RESULT_BYTES // (1024 * 1024)} MiB export limit. Add a LIMIT clause or export a smaller result.",
                        })
                    except Exception as exc:
                        self._json(400, {"ok": False, "error": _database_error(exc)})

            def _transaction(self, session, data):
                action = str(data.get("action", "")).lower()
                if action not in {"commit", "rollback"}:
                    self._json(400, {"ok": False, "error": "Action must be commit or rollback."})
                    return
                with session.lock:
                    if session.conn is None:
                        self._json(400, {"ok": False, "error": "Connect to MySQL first."})
                        return
                    if action == "commit" and owner.governor.read_only:
                        message = "Read-only policy blocks COMMIT because it could persist pending changes. Roll back, or disable read-only mode if this commit is intentional."
                        owner.governor.record_decision("COMMIT", "block", message, "transaction", "high")
                        self._json(403, {"ok": False, "error": message, "governance_blocked": True})
                        return
                    try:
                        getattr(session.conn, action)()
                        self._json(200, {"ok": True, "message": action.capitalize() + " completed."})
                    except Exception as exc:
                        self._json(400, {"ok": False, "error": _database_error(exc)})

        try:
            self.httpd = _BoundedThreadingHTTPServer((self.bind_host, self.port_requested), Handler)
        except OSError:
            # Avoid a dead end if another app already uses the default port.
            self.httpd = _BoundedThreadingHTTPServer((self.bind_host, 0), Handler)
        cert_path, key_path, self.certificate_fingerprint = _create_tls_identity(
            self.temp_dir.name, self.bind_host
        )
        tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
        tls_context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        self.httpd.tls_context = tls_context
        self.port = self.httpd.server_address[1]
        self.url = f"https://{self.bind_host}:{self.port}/"
        self.allowed_hosts = {"localhost", "127.0.0.1", self.bind_host.lower()}
        self._running = False
        self._closed = False

    def _purge_expired_sessions(self):
        now = time.monotonic()
        expired = [token for token, s in self.sessions.items() if now - s.last_active > IDLE_TIMEOUT_SECONDS]
        for token in expired:
            session = self.sessions.pop(token, None)
            if session:
                session.close()

    def start(self):
        if not self.governor.feature_enabled("mobile_companion"):
            raise RuntimeError("Feature Governance has disabled the mobile companion.")
        if self._closed:
            raise RuntimeError("This mobile companion has already been stopped.")
        if self._running:
            return
        self._running = True
        self._serve_thread = threading.Thread(target=self.httpd.serve_forever, name="mysql-idle-mobile-http", daemon=True)
        self._serve_thread.start()

    def stop(self):
        if self._closed:
            return
        was_running = self._running
        self._running = False
        try:
            if was_running:
                self.httpd.shutdown()
        finally:
            self.httpd.server_close()
            with self.sessions_lock:
                for session in self.sessions.values():
                    session.close()
                self.sessions.clear()
            self.pairing_code = ""
            with self.attempts_lock:
                self.attempts.clear()
            try:
                self.temp_dir.cleanup()
            except OSError:
                pass
            self._closed = True

    @property
    def running(self):
        return self._running


def _database_error(exc):
    args = getattr(exc, "args", ())
    if len(args) >= 2 and isinstance(args[0], int):
        return f"MySQL error {args[0]}: {args[1]}"
    return str(exc)[:1000] or exc.__class__.__name__
