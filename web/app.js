'use strict';
function setMode(){
  for(const id of ['case','message','context'])$(id).disabled=!!activeIssue;
  $('followup-area').hidden=!activeIssue;
  $('generate').textContent=activeIssue?'生成新版本':'生成回复草稿';
  $('active-issue').textContent=activeIssue?'正在处理：'+activeIssue+' · 原问题保留，后续信息请填下方':'新问题 · 首次生成成功后自动保存';
}
async function get(path){const r=await fetch(path,{headers:{'X-Workbench-Token':boot.token}});const out=await r.json();if(!r.ok)throw Error(out.error||'读取失败');return out}
function dateText(value){const d=new Date(value);return Number.isNaN(d.getTime())?'时间未记录':d.toLocaleString('zh-CN',{hour12:false})}
function drawHistory(){
 const q=$('search-history').value.trim().toLowerCase(),status=$('filter-history').value;
 const items=historyItems.filter(x=>x.message.toLowerCase().includes(q)&&(!status||x.status===status));
 $('history-info').textContent=items.length?`找到 ${items.length} 条问题`:(historyItems.length?'没有匹配的记录，请调整关键词或状态。':'还没有问题记录。首次生成成功后会显示在这里。');
 $('history-list').replaceChildren();
 for(const x of items){const li=document.createElement('li'),b=document.createElement('button'),title=document.createElement('strong'),meta=document.createElement('span');b.type='button';b.disabled=pending;b.setAttribute('aria-current',String(activeIssue===x.issue_id));title.textContent=x.message;meta.textContent=`${x.status} · ${x.versions} 个版本 · ${x.synthetic?'模拟案例':'自定义输入'} · 创建 ${dateText(x.created_at)} · 更新 ${dateText(x.updated_at)}`;b.append(title,meta);b.onclick=()=>openIssue(x.issue_id);li.append(b);$('history-list').append(li);}
}
async function refreshHistory(){try{historyItems=(await get('/api/history')).issues;drawHistory()}catch(err){$('history-info').textContent='读取失败：'+err.message+' 可点击刷新记录重试。'}}
function drawTimeline(data){$('timeline-panel').hidden=false;$('timeline').replaceChildren();for(const [index,v]of data.versions.entries()){
 const item=document.createElement('details'),heading=document.createElement('summary');heading.textContent=`版本 ${index+1} · ${dateText(v.record.created_at)} · ${v.reviews.length?'已保存审核':'待审核'}`;item.append(heading);
 const fields=[['学生问题',v.record.input.message],['当时背景',v.record.input.context],['老师核查结果',v.record.input.teacher_result],['AI 原始草稿',v.record.draft.student_reply]];
 for(const r of v.reviews)fields.push([`审核 · ${dateText(r.saved_at)} · ${r.status}`,r.reply+'\n备注：'+(r.note||'无')]);
 for(const [label,value]of fields){const h=document.createElement('h3'),p=document.createElement('p');h.textContent=label;p.textContent=value;item.append(h,p)}$('timeline').append(item);
}}
async function loadTimeline(id){try{const data=await get('/api/issue?id='+encodeURIComponent(id));if(activeIssue===id)drawTimeline(data)}catch(err){$('timeline-panel').hidden=false;$('timeline').textContent='时间线读取失败：'+err.message;}}
async function openIssue(id){
 if(pending)return;if(dirty&&!confirm('打开记录会放弃尚未保存的修改，是否继续？'))return;
 pending=true;lockReview(true);$('inputs').disabled=true;
 try{const data=await get('/api/issue?id='+encodeURIComponent(id)),v=data.versions.at(-1),c=v.record.input;
 $('case').value=c.id;$('message').value=c.message;$('context').value=c.context;$('teacher').value=c.teacher_result;$('followup').value='';
 render({...v,revision:data.revision});const review=v.reviews.at(-1);if(review){$('reply').value=review.reply;$('note').value=review.note;$('status').value=review.status;$('saved').textContent='已恢复最近一次审核记录。复制或再次保存前请核对确认。';count();}
 drawTimeline(data);drawHistory();notify('已打开问题。可审核最新回复，或补充信息继续处理。');$('active-issue').scrollIntoView({block:'start'});
 }catch(err){notify(err.message,true)}finally{pending=false;lockReview(false);$('inputs').disabled=false;setMode();}
}
const $=id=>document.getElementById(id);
let boot,run=null,original='',dirty=false,stale=false,pending=false,activeIssue=null,revision='',historyItems=[];
const notify=(text,error=false)=>{$('notice').textContent=text;$('notice').classList.toggle('error',error)};
function lockReview(value){for(const id of ['reply','reviewed','copy','save','status','note','new-issue','refresh-history','search-history','filter-history'])$(id).disabled=value;for(const b of $('history-list').querySelectorAll('button'))b.disabled=value}
function count(){ $('length').textContent=`${$('reply').value.length} 字符`;$('edited').textContent=$('reply').value===original?'原始草稿':'已修改'; }
function list(id,items){$(id).replaceChildren(...items.map(s=>{const li=document.createElement('li');li.textContent=s;return li}))}
function loadCase(){const c=boot.cases.find(c=>c.id===$('case').value);$('message').value=c.message;$('context').value=c.context;$('teacher').value=c.teacher_result;dirty=true;stale=!!run;$('freshness').hidden=!stale;$('reviewed').checked=false;notify(run?'已切换案例。右侧仍是上次结果，请重新生成。':'可先用模拟案例体验；每次生成会调用模型 API。')}
async function post(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Workbench-Token':boot.token},body:JSON.stringify(data)});const out=await r.json();if(!r.ok)throw new Error(out.error||'请求失败');return out}
function render(out){run=out;activeIssue=out.record.issue_id||out.run_id;revision=out.revision||out.run_id+':';$('context').value=out.record.input.context;setMode();original=out.record.draft.student_reply;stale=false;$('freshness').hidden=true;dirty=false;$('reply').value=original;$('reviewed').checked=false;$('note').value='';$('result').hidden=false;$('empty').hidden=true;$('status').value=out.record.draft.suggested_status;$('elapsed').textContent=`本次生成 ${out.record.elapsed_seconds} 秒`;list('checks',out.record.draft.assistant_checks);list('missing',out.record.draft.missing_info);const cards=out.record.source_cards;$('evidence').replaceChildren();if(!out.record.draft.evidence.length){$('evidence').textContent='无可用规则引用；不能据此解释未知原因。'}for(const e of out.record.draft.evidence){const c=cards.find(c=>c.id===e.knowledge_id),div=document.createElement('div');div.className='source';for(const text of [c.id+' · '+c.title,e.quote,c.source+' · '+c.verification]){const p=document.createElement('p');p.textContent=text;div.append(p)}$('evidence').append(div)}$('saved').textContent='原始草稿已保存在本机；修改后请保存审核记录。';count()}
function canReview(){if(pending)return false;if(!run||stale){notify('请先针对当前输入生成回复。',true);return false}if(!$('reviewed').checked){notify('请先核对回复并勾选确认。',true);return false}if(!$('reply').value.trim()){notify('回复不能为空。',true);return false}return true}
$('question-form').addEventListener('submit',async e=>{e.preventDefault();if(pending)return;if(activeIssue&&!$('followup').value.trim()){notify('请填写后续补充信息，再生成新版本。',true);$('followup').focus();return}if(dirty&&!confirm('重新生成会替换未保存的修改，是否继续？'))return;pending=true;lockReview(true);$('inputs').disabled=true;$('copy').disabled=true;$('save').disabled=true;$('reply').disabled=true;$('reviewed').disabled=true;$('output').setAttribute('aria-busy','true');let seconds=0;notify('正在生成，通常需要数十秒，请勿重复提交。');const timer=setInterval(()=>notify(`正在生成 · 已等待 ${++seconds} 秒`),1000);try{const out=await post('/api/generate',{case_id:$('case').value,message:$('message').value,context:activeIssue?'':$('context').value,teacher_result:$('teacher').value,issue_id:activeIssue,revision,followup:$('followup').value});render(out);$('followup').value='';refreshHistory();loadTimeline(activeIssue);notify('草稿已生成，请核对事实，再修改或复制。')}catch(err){notify(err.message,true)}finally{clearInterval(timer);pending=false;lockReview(false);$('inputs').disabled=false;$('copy').disabled=false;$('save').disabled=false;$('reply').disabled=false;$('reviewed').disabled=false;$('output').setAttribute('aria-busy','false')}});
for(const id of ['message','context','teacher','followup'])$(id).addEventListener('input',()=>{dirty=true;stale=!!run;$('freshness').hidden=!stale;$('reviewed').checked=false;notify(run?'输入已改变，请重新生成；右侧保留上次回复供参考。':'已修改输入。生成前请确认内容已脱敏。')});
$('case').addEventListener('change',loadCase);
$('reply').addEventListener('input',()=>{dirty=true;$('reviewed').checked=false;count()});
for(const id of ['status','note'])$(id).addEventListener('input',()=>{dirty=true});
$('copy').onclick=async()=>{if(!canReview())return;try{await navigator.clipboard.writeText($('reply').value);notify('已复制回复，请自行发送。')}catch{$('reply').focus();$('reply').select();notify('请按 Ctrl+C 或使用系统复制菜单复制选中文字。')}};
$('save').onclick=async()=>{if(!canReview())return;if($('status').value==='已解决'&&!$('note').value.trim()){notify('标记已解决前，请填写解决依据。',true);return}pending=true;lockReview(true);$('inputs').disabled=true;try{const out=await post('/api/review',{run_id:run.run_id,reply:$('reply').value,status:$('status').value,note:$('note').value,reviewed:true,revision});revision=out.revision;dirty=false;refreshHistory();loadTimeline(activeIssue);$('saved').textContent='已保存到本机：'+out.file;notify('审核记录已保存，原始草稿仍保留。')}catch(err){notify(err.message,true)}finally{pending=false;lockReview(false);$('inputs').disabled=false}};
window.addEventListener('beforeunload',e=>{if(dirty||pending){e.preventDefault();e.returnValue=''}});
(async()=>{try{const r=await fetch('/api/bootstrap');if(!r.ok)throw new Error('无法连接本机服务');boot=await r.json();for(const c of boot.cases)$('case').add(new Option(c.id+' · '+({'F010':'学情未掌握','F009':'重复推题','F004':'多次尝试仍不会'}[c.id]),c.id));for(const t of boot.teacher_results)$('teacher').add(new Option(t,t));for(const s of boot.statuses){$('status').add(new Option(s,s));$('filter-history').add(new Option(s,s));}$('case').value='F010';loadCase();dirty=false;refreshHistory();$('model').textContent=boot.model;$('generate').disabled=!boot.ready;if(!boot.ready)notify(boot.problem,true)}catch(err){notify('页面未能载入：'+err.message+'。请确认本机服务运行后刷新。',true)}})();

$('refresh-history').onclick=()=>{if(!pending)refreshHistory()};
$('search-history').oninput=drawHistory;
$('filter-history').onchange=drawHistory;
$('new-issue').onclick=()=>{if(pending)return;if(dirty&&!confirm('新建问题会放弃未保存的修改，是否继续？'))return;activeIssue=null;run=null;revision='';stale=false;dirty=false;$('followup').value='';$('result').hidden=true;$('empty').hidden=false;$('timeline-panel').hidden=true;setMode();loadCase();dirty=false;drawHistory();$('message').focus();};
