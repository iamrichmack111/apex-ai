const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

let token = localStorage.getItem("apexToken") || localStorage.getItem("richmackToken") || "";
let username = localStorage.getItem("apexUsername") || localStorage.getItem("richmackUsername") || "";
let authMode = "login";
let currentConversationId = null;
let currentConversation = null;
let defaultModel = "";
let activeController = null;
let isStreaming = false;
let appMode = "chat";
let chatMenuConversation = null;

const DEFAULT_PREFS = {
  theme:"nebula", accent:"electric", fontSize:15, density:"comfortable", chatWidth:800,
  animations:true, timestamps:false, avatars:true, enterToSend:true, finishSound:false,
  backgroundMode:"aurora", backgroundIntensity:.65, backgroundSpeed:1, glassStrength:.72,
  cursorGlow:true, backgroundBlur:18,
  responseMode:"fast", temperature:.55, maxTokens:480, contextWindow:4096, thinking:false,
  systemPrompt:"You are Apex AI, a capable private local assistant. Be direct, clear, useful, and concise unless the user asks for detail.",
  imageSize:"512x512", imageSteps:6, imageStyle:"auto", useKnowledge:true, knowledgeResults:5,
  intelligenceMode:"auto", autoModelRouting:true, maxAutoModelB:9, adaptiveThinking:true,
  longTermMemory:true, autoLearnMemory:true, conversationSummaries:true, embeddingRerank:true, memoryResults:5,
  imageNegativePrompt:"worst quality, low quality, lowres, blurry, deformed, malformed anatomy, extra limbs, extra fingers, fused fingers, bad hands, bad face, duplicate, text, watermark, logo"
};
let prefs={...DEFAULT_PREFS};
let visualEngine=null;

function authHeaders(extra={}){return {...extra,...(token?{Authorization:`Bearer ${token}`}:{})}}
async function api(url,options={}){options.headers=authHeaders(options.headers||{});const r=await fetch(url,options);if(r.status===401){logoutLocal();throw new Error("Please log in again.")}return r}
function escapeHtml(s=""){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]))}
function renderMarkdown(text=""){
  const escaped=escapeHtml(text),parts=escaped.split(/```/);
  return parts.map((part,i)=>{
    if(i%2===1){let code=part,n=code.indexOf("\n");if(n>-1&&n<30)code=code.slice(n+1);return `<pre><code>${code}</code></pre>`}
    let out=part.replace(/`([^`\n]+)`/g,"<code>$1</code>").replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>");
    return out.split(/\n{2,}/).map(p=>`<p>${p.replace(/\n/g,"<br>")}</p>`).join("")
  }).join("")
}
function formatTime(iso){if(!iso)return "";try{return new Date(iso).toLocaleTimeString([],{hour:"numeric",minute:"2-digit"})}catch{return ""}}
function toast(message,type=""){const el=document.createElement("div");el.className=`toast ${type}`;el.textContent=message;$("#toastHost").appendChild(el);setTimeout(()=>el.remove(),2600)}
function downloadJSON(data,filename){const blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"}),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
function closeFloatingMenus(){$("#plusMenu").classList.add("hidden");$("#chatMenu").classList.add("hidden");$("#profileMenu").classList.add("hidden")}
function openAnchoredMenu(menu,anchor,placement="below"){closeFloatingMenus();menu.classList.remove("hidden");const r=anchor.getBoundingClientRect(),mr=menu.getBoundingClientRect();let left=Math.min(window.innerWidth-mr.width-8,Math.max(8,r.left)),top=placement==="above"?r.top-mr.height-7:r.bottom+7;if(top+mr.height>window.innerHeight-8)top=r.top-mr.height-7;menu.style.left=`${left}px`;menu.style.top=`${Math.max(8,top)}px`}
function logoutLocal(){token="";username="";["apexToken","apexUsername","richmackToken","richmackUsername"].forEach(k=>localStorage.removeItem(k));$("#app").classList.add("hidden");$("#authScreen").classList.remove("hidden")}
function scrollBottom(){const el=$("#chatScroll");el.scrollTop=el.scrollHeight}
function playFinishSound(){if(!prefs.finishSound)return;try{const Ctx=window.AudioContext||window.webkitAudioContext,ctx=new Ctx(),osc=ctx.createOscillator(),gain=ctx.createGain();osc.frequency.value=560;gain.gain.value=.022;osc.connect(gain);gain.connect(ctx.destination);osc.start();osc.stop(ctx.currentTime+.08);osc.onended=()=>ctx.close()}catch{}}

function applyPrefs(){
  document.documentElement.dataset.theme=prefs.theme;
  document.documentElement.dataset.accent=prefs.accent;
  document.documentElement.style.setProperty("--font-size",`${prefs.fontSize}px`);
  document.documentElement.style.setProperty("--chat-width",`${prefs.chatWidth}px`);
  document.documentElement.style.setProperty("--glass-opacity",String(prefs.glassStrength));
  document.documentElement.style.setProperty("--glass-blur",`${prefs.backgroundBlur}px`);
  document.body.classList.toggle("no-animations",!prefs.animations);
  document.body.classList.toggle("compact",prefs.density==="compact");
  document.body.classList.toggle("spacious",prefs.density==="spacious");
  document.body.classList.toggle("hide-avatars",!prefs.avatars);
  $("#cursorGlow").style.opacity=prefs.cursorGlow?"0.8":"0";
  $("#imageStyle").value=prefs.imageStyle||"auto";
  $("#imageSize").value=prefs.imageSize;
  $("#imageSteps").value=String(prefs.imageSteps);
  updateModeHint();
  if(visualEngine){
    visualEngine.setMode(prefs.backgroundMode);
    visualEngine.setIntensity(prefs.backgroundIntensity);
    visualEngine.setSpeed(prefs.backgroundSpeed);
    visualEngine.setBlur(prefs.backgroundBlur);
    visualEngine.running=!!prefs.animations;
  }
}
async function loadSettings(){
  try{const r=await api("/api/settings"),d=await r.json();prefs={...DEFAULT_PREFS,...(d.settings||{})}}catch{prefs={...DEFAULT_PREFS}}
  applyPrefs()
}
async function saveSettings(){
  readSettingsForm();applyPrefs();
  const r=await api("/api/settings",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({settings:prefs})});
  if(!r.ok)throw new Error(await r.text());
  $("#settingsSaved").textContent="Saved";toast("Settings saved","success");setTimeout(()=>$("#settingsSaved").textContent="",1800)
}
function fillSettingsForm(){
  $("#enterToSend").checked=!!prefs.enterToSend;$("#timestamps").checked=!!prefs.timestamps;$("#avatars").checked=!!prefs.avatars;$("#animations").checked=!!prefs.animations;$("#cursorGlowToggle").checked=!!prefs.cursorGlow;$("#finishSound").checked=!!prefs.finishSound;
  $("#fontSize").value=prefs.fontSize;$("#fontSizeValue").textContent=prefs.fontSize;
  $("#chatWidth").value=prefs.chatWidth;$("#chatWidthValue").textContent=prefs.chatWidth;
  $("#glassStrength").value=Math.round(prefs.glassStrength*100);$("#glassStrengthValue").textContent=Math.round(prefs.glassStrength*100);
  $("#backgroundIntensity").value=Math.round(prefs.backgroundIntensity*100);$("#backgroundIntensityValue").textContent=Math.round(prefs.backgroundIntensity*100);
  $("#backgroundSpeed").value=Math.round(prefs.backgroundSpeed*100);$("#backgroundSpeedValue").textContent=Math.round(prefs.backgroundSpeed*100);
  $("#backgroundBlur").value=prefs.backgroundBlur;$("#backgroundBlurValue").textContent=prefs.backgroundBlur;
  $("#temperature").value=prefs.temperature;$("#temperatureValue").textContent=Number(prefs.temperature).toFixed(2);
  $("#maxTokens").value=prefs.maxTokens;$("#maxTokensValue").textContent=prefs.maxTokens;
  $("#contextWindow").value=String(prefs.contextWindow);$("#thinking").checked=!!prefs.thinking;$("#systemPrompt").value=prefs.systemPrompt;
  $("#defaultImageStyle").value=prefs.imageStyle||"auto";$("#defaultImageSize").value=prefs.imageSize;$("#imageNegativePrompt").value=prefs.imageNegativePrompt;
  $("#useKnowledge").checked=!!prefs.useKnowledge;$("#knowledgeResults").value=Number(prefs.knowledgeResults||5);$("#knowledgeResultsValue").textContent=Number(prefs.knowledgeResults||5);
  $("#autoModelRouting").checked=!!prefs.autoModelRouting;$("#maxAutoModelB").value=Number(prefs.maxAutoModelB||9);$("#maxAutoModelBValue").textContent=Number(prefs.maxAutoModelB||9);
  $("#adaptiveThinking").checked=!!prefs.adaptiveThinking;$("#longTermMemory").checked=!!prefs.longTermMemory;$("#autoLearnMemory").checked=!!prefs.autoLearnMemory;$("#conversationSummaries").checked=!!prefs.conversationSummaries;$("#embeddingRerank").checked=!!prefs.embeddingRerank;
  $("#memoryResults").value=Number(prefs.memoryResults||5);$("#memoryResultsValue").textContent=Number(prefs.memoryResults||5);
  $$("#intelligenceModeControl button").forEach(b=>b.classList.toggle("active",b.dataset.intelligenceMode===prefs.intelligenceMode));
  $$("#themeGrid button").forEach(b=>b.classList.toggle("selected",b.dataset.themeChoice===prefs.theme));
  $$("#accentGrid button").forEach(b=>b.classList.toggle("selected",b.dataset.accentChoice===prefs.accent));
  $$("#backgroundModes button").forEach(b=>b.classList.toggle("selected",b.dataset.bgMode===prefs.backgroundMode));
  $$("#densityControl button").forEach(b=>b.classList.toggle("active",b.dataset.density===prefs.density));
  $$("#responseMode button").forEach(b=>b.classList.toggle("active",b.dataset.mode===prefs.responseMode));
  $$("#imageStepsControl button").forEach(b=>b.classList.toggle("active",Number(b.dataset.imageSteps)===Number(prefs.imageSteps)))
}
function readSettingsForm(){
  prefs.enterToSend=$("#enterToSend").checked;prefs.timestamps=$("#timestamps").checked;prefs.avatars=$("#avatars").checked;prefs.animations=$("#animations").checked;prefs.cursorGlow=$("#cursorGlowToggle").checked;prefs.finishSound=$("#finishSound").checked;
  prefs.fontSize=Number($("#fontSize").value);prefs.chatWidth=Number($("#chatWidth").value);prefs.glassStrength=Number($("#glassStrength").value)/100;
  prefs.backgroundIntensity=Number($("#backgroundIntensity").value)/100;prefs.backgroundSpeed=Number($("#backgroundSpeed").value)/100;prefs.backgroundBlur=Number($("#backgroundBlur").value);
  prefs.temperature=Number($("#temperature").value);prefs.maxTokens=Number($("#maxTokens").value);prefs.contextWindow=Number($("#contextWindow").value);prefs.thinking=$("#thinking").checked;prefs.systemPrompt=$("#systemPrompt").value;
  prefs.imageStyle=$("#defaultImageStyle").value;prefs.imageSize=$("#defaultImageSize").value;prefs.imageNegativePrompt=$("#imageNegativePrompt").value;
  prefs.useKnowledge=$("#useKnowledge").checked;prefs.knowledgeResults=Number($("#knowledgeResults").value);
  prefs.autoModelRouting=$("#autoModelRouting").checked;prefs.maxAutoModelB=Number($("#maxAutoModelB").value);prefs.adaptiveThinking=$("#adaptiveThinking").checked;
  prefs.longTermMemory=$("#longTermMemory").checked;prefs.autoLearnMemory=$("#autoLearnMemory").checked;prefs.conversationSummaries=$("#conversationSummaries").checked;prefs.embeddingRerank=$("#embeddingRerank").checked;prefs.memoryResults=Number($("#memoryResults").value)
}
function updateIntelligenceBadge(){const b=$("#intelligenceBadgeText");if(b)b.textContent=String(prefs.intelligenceMode||"auto").toUpperCase()}
function updateModeHint(){updateIntelligenceBadge();if(appMode==="image")$("#modeHint").textContent=`Image · ${prefs.imageSteps} steps`;else $("#modeHint").textContent=`${prefs.responseMode[0].toUpperCase()+prefs.responseMode.slice(1)} · ${prefs.maxTokens} tokens`}

function animateMessage(row){
  if(!prefs.animations||!row.animate)return;
  row.animate([{opacity:0,transform:"translateY(8px) scale(.995)"},{opacity:1,transform:"none"}],{duration:220,easing:"cubic-bezier(.2,.8,.2,1)"})
}
function makeMessage(role,content="",imageUrl=null,messageType="text",createdAt=null){
  $("#emptyState").style.display="none";const row=document.createElement("div");row.className=`message ${role}`;row.dataset.role=role;row.dataset.content=content;
  row.innerHTML=`<div class="message-avatar">${role==="user"?"YOU":"A"}</div><div><div class="message-head"><span class="message-name">${role==="user"?"You":"Apex AI"}</span><span class="message-time ${prefs.timestamps?"":"hidden"}">${formatTime(createdAt)}</span></div><div class="message-body"></div><div class="message-actions"></div></div>`;
  const body=row.querySelector(".message-body"),actions=row.querySelector(".message-actions");
  if(messageType==="image"&&imageUrl){
    body.innerHTML=`<p>${escapeHtml(content)}</p><img class="generated-image" src="${imageUrl}" alt="${escapeHtml(content)}">`;
    actions.innerHTML=`<button class="message-action" data-act="open-image">Open image</button><button class="message-action" data-act="copy">Copy prompt</button>`;
    actions.querySelector('[data-act="open-image"]').onclick=()=>window.open(imageUrl,"_blank")
  }else{
    body.innerHTML=renderMarkdown(content);
    if(role==="assistant"){actions.innerHTML=`<button class="message-action" data-act="copy">Copy</button><button class="message-action" data-act="regenerate">Regenerate</button>`;actions.querySelector('[data-act="regenerate"]').onclick=()=>regenerateLast()}
    else{actions.innerHTML=`<button class="message-action" data-act="copy">Copy</button><button class="message-action" data-act="edit">Edit & resend</button>`;actions.querySelector('[data-act="edit"]').onclick=()=>{$("#messageInput").value=content;autoResize();$("#messageInput").focus()}}
  }
  actions.querySelector('[data-act="copy"]').onclick=async()=>{await navigator.clipboard.writeText(content);toast("Copied","success")};
  $("#messages").appendChild(row);animateMessage(row);scrollBottom();return {row,body,actions}
}
function makeImageLoading(){ $("#emptyState").style.display="none";const row=document.createElement("div");row.className="message assistant";row.innerHTML=`<div class="message-avatar">A</div><div><div class="message-head"><span class="message-name">Apex AI</span></div><div class="image-loading">Creating image…</div></div>`;$("#messages").appendChild(row);animateMessage(row);scrollBottom();return row }

async function loadConfig(){const c=await fetch("/api/config").then(r=>r.json());defaultModel=c.default_model;document.title=c.title}
async function loadModels(prefer=null){const r=await api("/api/models"),d=await r.json(),sel=$("#modelSelect"),previous=prefer||sel.value||localStorage.getItem("apexLastModel")||"";sel.innerHTML="";if(!d.models.length){const o=document.createElement("option");o.value="";o.textContent="No model installed";sel.appendChild(o)}else{for(const name of d.models){const o=document.createElement("option");o.value=name;o.textContent=name;sel.appendChild(o)}if(d.models.includes(previous))sel.value=previous;else if(d.models.includes(defaultModel))sel.value=defaultModel;else sel.value=d.models[0]}if(sel.value)localStorage.setItem("apexLastModel",sel.value)}
async function checkHealth(){try{const d=await fetch("/api/health").then(r=>r.json()),ok=d.ollama==="ok";$("#statusDot").className="status-dot "+(ok?"ok":"bad");$("#statusText").textContent=ok?"Ollama connected":"Ollama unavailable";$("#imageEngineDot").className="mini-dot "+(d.image==="ok"?"ok":"");$("#imageStatus").textContent=d.image==="ok"?"Tiny-SD ready":"Image engine unavailable"}catch{$("#statusDot").className="status-dot bad";$("#statusText").textContent="Backend unavailable";$("#imageStatus").textContent="Image engine unavailable"}}

function renderConversationRows(rows){const list=$("#conversationList");list.innerHTML="";const pinned=rows.filter(c=>Number(c.pinned)===1),recent=rows.filter(c=>Number(c.pinned)!==1);const addSection=(label,items)=>{if(!items.length)return;const h=document.createElement("div");h.className="chat-section-label";h.textContent=label;list.appendChild(h);for(const c of items){const item=document.createElement("div");item.className="conversation-item"+(c.id===currentConversationId?" active":"");item.dataset.id=c.id;item.innerHTML=`${Number(c.pinned)===1?'<span class="conversation-pin">◆</span>':'<span class="conversation-pin"></span>'}<span class="conversation-title"></span><button class="conversation-more">•••</button>`;item.querySelector(".conversation-title").textContent=c.title;item.querySelector(".conversation-title").onclick=()=>loadConversation(c.id);item.querySelector(".conversation-more").onclick=e=>{e.stopPropagation();chatMenuConversation=c;$("#chatPinLabel").textContent=Number(c.pinned)===1?"Unpin chat":"Pin chat";openAnchoredMenu($("#chatMenu"),e.currentTarget,"below")};list.appendChild(item)}};addSection("Pinned",pinned);addSection("Recent",recent)}
async function refreshConversations(q=""){const r=await api(`/api/conversations${q?`?q=${encodeURIComponent(q)}`:""}`),rows=await r.json();renderConversationRows(rows)}
async function newConversation(){const r=await api("/api/conversations",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:"New chat",model:$("#modelSelect").value||defaultModel})}),d=await r.json();currentConversationId=d.id;currentConversation=d;$("#messages").innerHTML="";$("#emptyState").style.display="";await refreshConversations($("#chatSearch").value.trim());$("#sidebar").classList.remove("open");$("#messageInput").focus()}
async function loadConversation(id){const r=await api(`/api/conversations/${id}`),d=await r.json();currentConversationId=id;currentConversation=d.conversation;$("#messages").innerHTML="";if([...$("#modelSelect").options].some(o=>o.value===d.conversation.model))$("#modelSelect").value=d.conversation.model;if(!d.messages.length)$("#emptyState").style.display="";else{$("#emptyState").style.display="none";for(const m of d.messages){const type=m.message_type||"text";if(type==="image_prompt")makeMessage("user",m.content,null,"text",m.created_at);else makeMessage(m.role,m.content,m.image_url,type,m.created_at)}}await refreshConversations($("#chatSearch").value.trim());$("#sidebar").classList.remove("open");scrollBottom()}
async function updateConversation(id,patch){const r=await api(`/api/conversations/${id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(patch)});if(!r.ok)throw new Error(await r.text());const d=await r.json();if(currentConversationId===id)currentConversation={...(currentConversation||{}),...d};await refreshConversations($("#chatSearch").value.trim());return d}
async function deleteConversation(id){await api(`/api/conversations/${id}`,{method:"DELETE"});if(currentConversationId===id){currentConversationId=null;currentConversation=null;$("#messages").innerHTML="";$("#emptyState").style.display=""}await refreshConversations($("#chatSearch").value.trim())}
async function exportConversation(id){const r=await api(`/api/conversations/${id}/export`),d=await r.json(),safe=(d.conversation?.title||"apex-chat").replace(/[^a-z0-9_-]+/gi,"_").slice(0,60);downloadJSON(d,`${safe}.json`)}
async function exportAll(){const r=await api("/api/export"),d=await r.json();downloadJSON(d,`apex-ai-export-${new Date().toISOString().slice(0,10)}.json`);toast("Export ready","success")}

function setBusy(on,allowStop=true){isStreaming=on;$("#sendBtn").classList.toggle("hidden",on&&allowStop);$("#stopBtn").classList.toggle("hidden",!(on&&allowStop));$("#messageInput").disabled=on}
function stopGeneration(){if(activeController)activeController.abort()}
function chatPayloadBase(){return {
  model:$("#modelSelect").value||defaultModel,system_prompt:prefs.systemPrompt,response_mode:prefs.responseMode,
  temperature:Number(prefs.temperature),max_tokens:Number(prefs.maxTokens),context_window:Number(prefs.contextWindow),thinking:!!prefs.thinking,
  use_knowledge:!!prefs.useKnowledge,knowledge_results:Number(prefs.knowledgeResults||5),
  intelligence_mode:prefs.intelligenceMode||"auto",auto_model_routing:!!prefs.autoModelRouting,max_auto_model_b:Number(prefs.maxAutoModelB||9),
  adaptive_thinking:!!prefs.adaptiveThinking,use_memory:!!prefs.longTermMemory,auto_learn_memory:!!prefs.autoLearnMemory,
  use_summary:!!prefs.conversationSummaries,embedding_rerank:!!prefs.embeddingRerank,memory_results:Number(prefs.memoryResults||5)
}}
function renderIntelligenceMeta(ai,d){
  let el=ai.row.querySelector(".intelligence-meta");
  if(!el){el=document.createElement("div");el.className="intelligence-meta";ai.body.parentElement.insertBefore(el,ai.actions)}
  const chips=[];
  if(d.mode)chips.push(`<span class="intelligence-chip primary">✦ ${escapeHtml(String(d.mode).toUpperCase())}</span>`);
  if(d.model)chips.push(`<span class="intelligence-chip">${d.routed?"Routed":"Model"}: ${escapeHtml(String(d.model))}</span>`);
  if(Number(d.knowledge_count)>0)chips.push(`<span class="intelligence-chip">${Number(d.knowledge_count)} knowledge</span>`);
  if(Number(d.memory_count)>0)chips.push(`<span class="intelligence-chip">${Number(d.memory_count)} memories</span>`);
  if(d.summary_used)chips.push(`<span class="intelligence-chip">long-chat summary</span>`);
  if(d.embedding_model)chips.push(`<span class="intelligence-chip">semantic rerank</span>`);
  if(d.calculator)chips.push(`<span class="intelligence-chip">calculator</span>`);
  el.innerHTML=chips.join("");
}
function renderIntelligencePhase(ai,phase){
  let el=ai.row.querySelector(".intelligence-meta");
  if(!el){el=document.createElement("div");el.className="intelligence-meta";ai.body.parentElement.insertBefore(el,ai.actions)}
  let phaseEl=el.querySelector(".phase");
  if(!phaseEl){phaseEl=document.createElement("span");phaseEl.className="intelligence-chip phase";el.appendChild(phaseEl)}
  const labels={drafting:"Building internal draft…",reviewing:"Reviewing answer…",reasoning:"Reasoning…",answering:"Answering…"};
  phaseEl.textContent=labels[phase]||phase;if(phase==="answering")setTimeout(()=>phaseEl.remove(),800);
}
async function consumeChatStream(r,ai){
  if(!r.ok)throw new Error(await r.text());
  const reader=r.body.getReader(),decoder=new TextDecoder();let buffer="",accumulated="",pending="",paintScheduled=false;
  const paint=()=>{paintScheduled=false;if(pending){accumulated+=pending;pending="";ai.body.innerHTML=renderMarkdown(accumulated);scrollBottom()}};
  while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});const events=buffer.split("\n\n");buffer=events.pop()||"";for(const evt of events){const line=evt.split("\n").find(x=>x.startsWith("data: "));if(!line)continue;const d=JSON.parse(line.slice(6));if(d.type==="token"){pending+=d.content;if(!paintScheduled){paintScheduled=true;setTimeout(paint,28)}}else if(d.type==="meta")renderIntelligenceMeta(ai,d);else if(d.type==="phase")renderIntelligencePhase(ai,d.phase);else if(d.type==="error")throw new Error(d.error)}}
  paint();return accumulated;
}
async function sendChat(text){const model=$("#modelSelect").value;if(!model){openModal("modelModal");return}if(!currentConversationId)await newConversation();makeMessage("user",text,null,"text",new Date().toISOString());const ai=makeMessage("assistant","",null,"text",new Date().toISOString());ai.body.classList.add("typing");activeController=new AbortController();setBusy(true,true);try{const r=await api("/api/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({conversation_id:currentConversationId,message:text,...chatPayloadBase()}),signal:activeController.signal});await consumeChatStream(r,ai);playFinishSound()}catch(err){if(err.name==="AbortError"){if(!ai.body.textContent.trim())ai.row.remove();else ai.body.innerHTML+=`<p><em>Stopped.</em></p>`}else ai.body.innerHTML=renderMarkdown(`**Error:** ${err.message}`)}finally{ai.body.classList.remove("typing");activeController=null;setBusy(false);await refreshConversations($("#chatSearch").value.trim());$("#messageInput").focus()}}
async function regenerateLast(){if(!currentConversationId||isStreaming)return;const ai=makeMessage("assistant","",null,"text",new Date().toISOString());ai.body.classList.add("typing");activeController=new AbortController();setBusy(true,true);try{const r=await api("/api/chat/regenerate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({conversation_id:currentConversationId,...chatPayloadBase()}),signal:activeController.signal});await consumeChatStream(r,ai);playFinishSound()}catch(err){if(err.name==="AbortError")ai.row.remove();else ai.body.innerHTML=renderMarkdown(`**Error:** ${err.message}`)}finally{ai.body.classList.remove("typing");activeController=null;setBusy(false);await refreshConversations($("#chatSearch").value.trim())}}
async function sendImage(text){if(!currentConversationId)await newConversation();makeMessage("user",text,null,"text",new Date().toISOString());const loading=makeImageLoading();setBusy(true,false);try{const [w,h]=$("#imageSize").value.split("x").map(Number),steps=Number($("#imageSteps").value),r=await api("/api/image/generate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({conversation_id:currentConversationId,prompt:text,negative_prompt:prefs.imageNegativePrompt,width:w,height:h,steps,style:$("#imageStyle").value||prefs.imageStyle||"auto"})}),d=await r.json();if(!r.ok)throw new Error(d.detail||"Image generation failed");loading.remove();makeMessage("assistant",`Generated image for: ${text}`,d.image_url,"image",new Date().toISOString());playFinishSound()}catch(err){const el=loading.querySelector(".image-loading");el.className="message-body";el.innerHTML=renderMarkdown(`**Image error:** ${err.message}`)}finally{setBusy(false);checkHealth();await refreshConversations($("#chatSearch").value.trim());$("#messageInput").focus()}}
async function sendMessage(textOverride=null){if(isStreaming)return;const input=$("#messageInput"),text=(textOverride??input.value).trim();if(!text)return;input.value="";autoResize();if(appMode==="image")await sendImage(text);else await sendChat(text)}

function bindSuggestions(){$$("#suggestions button").forEach(b=>b.onclick=()=>sendMessage(b.dataset.prompt))}
function setAppMode(mode){appMode=mode;$("#chatModeBtn").classList.toggle("active",mode==="chat");$("#imageModeBtn").classList.toggle("active",mode==="image");$("#imageOptions").classList.toggle("hidden",mode!=="image");if(mode==="image"){$("#heroTitle").textContent="Create something visual";$("#heroSubtitle").textContent="Higher-quality local images with DreamShaper LCM.";$("#messageInput").placeholder="Describe an image";$("#suggestions").innerHTML=`<button data-prompt="A cinematic rainy city street at night, neon reflections, realistic photography" class="ripple"><span class="suggestion-icon">▧</span><strong>Cinematic photo</strong><small>Rainy neon city</small></button><button data-prompt="A friendly robot reading a book in a cozy library, detailed digital illustration" class="ripple"><span class="suggestion-icon">✦</span><strong>Illustration</strong><small>Robot in a library</small></button><button data-prompt="Minimalist product photo of black wireless headphones on a clean desk, soft studio lighting" class="ripple"><span class="suggestion-icon">◫</span><strong>Product shot</strong><small>Clean studio photography</small></button><button data-prompt="Futuristic DevOps command center, multiple screens, dark modern office, cinematic" class="ripple"><span class="suggestion-icon">◇</span><strong>Concept art</strong><small>DevOps command center</small></button>`}else{$("#heroTitle").textContent="What do you want to build?";$("#heroSubtitle").textContent="Fast local AI with a visual interface that actually feels alive.";$("#messageInput").placeholder="Message Apex AI";$("#suggestions").innerHTML=`<button data-prompt="Explain Kubernetes deployments in simple terms." class="ripple"><span class="suggestion-icon">⌘</span><strong>Explain Kubernetes</strong><small>Make a complex topic simple</small></button><button data-prompt="Write a clean FastAPI app with comments and error handling." class="ripple"><span class="suggestion-icon">‹/›</span><strong>Build something</strong><small>Generate working code</small></button><button data-prompt="Help me design an impressive DevOps portfolio project." class="ripple"><span class="suggestion-icon">◇</span><strong>Plan a project</strong><small>Architecture and milestones</small></button><button data-prompt="Give me a Linux troubleshooting checklist for a slow server." class="ripple"><span class="suggestion-icon">⚙</span><strong>Troubleshoot</strong><small>Work through a problem</small></button>`}bindSuggestions();bindRipples();updateModeHint()}
function autoResize(){const i=$("#messageInput");i.style.height="auto";i.style.height=Math.min(i.scrollHeight,190)+"px"}
function openModal(id){closeFloatingMenus();$("#"+id).classList.remove("hidden")}
function closeModal(id){$("#"+id).classList.add("hidden")}
function openSettings(tab="general"){fillSettingsForm();switchSettingsTab(tab);openModal("settingsModal");refreshKnowledgeStatus();refreshIntelligenceStatus()}
function switchSettingsTab(tab){$$("#settingsNav button").forEach(b=>b.classList.toggle("active",b.dataset.settingsTab===tab));$$(".settings-panel").forEach(p=>p.classList.toggle("active",p.dataset.panel===tab))}
function showRename(c){chatMenuConversation=c||currentConversation;if(!chatMenuConversation)return;$("#renameInput").value=chatMenuConversation.title||"";openModal("renameModal");setTimeout(()=>{$("#renameInput").focus();$("#renameInput").select()},30)}
async function saveRename(){if(!chatMenuConversation)return;await updateConversation(chatMenuConversation.id,{title:$("#renameInput").value});closeModal("renameModal");toast("Chat renamed","success")}

async function installModel(){const model=$("#modelNameInput").value.trim();if(!model)return;$("#installModelBtn").disabled=true;$("#pullProgress").classList.remove("hidden");$("#pullBar").style.width="3%";$("#pullText").textContent=`Installing ${model}…`;try{const r=await api("/api/models/pull",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({model})});if(!r.ok)throw new Error(await r.text());const reader=r.body.getReader(),decoder=new TextDecoder();let buffer="";while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});const events=buffer.split("\n\n");buffer=events.pop()||"";for(const evt of events){const line=evt.split("\n").find(x=>x.startsWith("data: "));if(!line)continue;const d=JSON.parse(line.slice(6));if(d.type==="error")throw new Error(d.error);if(d.total&&d.completed){const pct=Math.max(3,Math.min(100,d.completed/d.total*100));$("#pullBar").style.width=pct+"%";$("#pullText").textContent=`${d.status||"Downloading"} · ${pct.toFixed(0)}%`}else if(d.status)$("#pullText").textContent=d.status}}$("#pullBar").style.width="100%";$("#pullText").textContent="Installed";await loadModels(model);toast("Model installed","success")}catch(err){$("#pullText").textContent="Error: "+err.message}finally{$("#installModelBtn").disabled=false}}

async function afterLogin(){$("#authScreen").classList.add("hidden");$("#app").classList.remove("hidden");$("#profileName").textContent=username;$("#profileAvatar").textContent=(username[0]||"U").toUpperCase();await loadSettings();await loadModels();await refreshConversations();await checkHealth()}
async function submitAuth(e){e.preventDefault();$("#authError").textContent="";try{const r=await fetch(`/api/auth/${authMode}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:$("#authUsername").value.trim(),password:$("#authPassword").value})}),d=await r.json();if(!r.ok)throw new Error(d.detail||"Authentication failed");token=d.token;username=d.username;localStorage.setItem("apexToken",token);localStorage.setItem("apexUsername",username);await afterLogin()}catch(err){$("#authError").textContent=err.message}}
function setAuthMode(mode){authMode=mode;$("#loginTab").classList.toggle("active",mode==="login");$("#signupTab").classList.toggle("active",mode==="signup");$("#authSubmit").textContent=mode==="login"?"Log in":"Create account";$("#authPassword").autocomplete=mode==="login"?"current-password":"new-password"}

function bindRipples(){
  $$(".ripple").forEach(el=>{
    if(el.dataset.rippleBound)return;
    el.dataset.rippleBound="1";
    el.addEventListener("click",e=>{
      if(!prefs.animations)return;
      const r=el.getBoundingClientRect(),size=Math.max(r.width,r.height)*1.2,w=document.createElement("span");
      w.className="ripple-wave";w.style.width=w.style.height=size+"px";w.style.left=(e.clientX-r.left-size/2)+"px";w.style.top=(e.clientY-r.top-size/2)+"px";el.appendChild(w);setTimeout(()=>w.remove(),600)
    })
  })
}


async function refreshKnowledgeStatus(){
  try{
    const r=await api("/api/knowledge/status"),d=await r.json();
    $("#knowledgeCount").textContent=Number(d.count||0).toLocaleString();
    $("#knowledgeReadyBadge").textContent=d.ready?`${Number(d.count||0).toLocaleString()} ready`:"Not installed";
    $("#knowledgeReadyBadge").classList.toggle("ready",!!d.ready);
  }catch{
    $("#knowledgeReadyBadge").textContent="Unavailable";
    $("#knowledgeReadyBadge").classList.remove("ready");
  }
}

async function testKnowledgeSearch(){
  const q=$("#knowledgeTestQuery").value.trim();
  if(!q)return;
  $("#knowledgeTestResults").innerHTML='<div class="knowledge-result"><p>Searching local knowledge…</p></div>';
  try{
    const r=await api(`/api/knowledge/search?q=${encodeURIComponent(q)}&limit=5`),d=await r.json();
    $("#knowledgeTestResults").innerHTML="";
    if(!(d.results||[]).length){
      $("#knowledgeTestResults").innerHTML='<div class="knowledge-result"><p>No matching records.</p></div>';
      return;
    }
    for(const item of d.results){
      const el=document.createElement("div");el.className="knowledge-result";
      el.innerHTML=`<strong>${escapeHtml(item.source)} · ${escapeHtml(String(item.question).slice(0,180))}</strong><p>${escapeHtml(String(item.answer).slice(0,500))}</p>`;
      $("#knowledgeTestResults").appendChild(el);
    }
  }catch(err){
    $("#knowledgeTestResults").innerHTML=`<div class="knowledge-result"><p>${escapeHtml(err.message)}</p></div>`;
  }
}

async function refreshIntelligenceStatus(){
  try{const r=await api("/api/intelligence/status"),d=await r.json();$("#memoryCount").textContent=Number(d.memory_count||0).toLocaleString();$("#summaryCount").textContent=Number(d.summary_count||0).toLocaleString();$("#installedModelCount").textContent=(d.installed_chat_models||[]).length;$("#embeddingBadge").textContent=d.embedding_model?`Embeddings: ${d.embedding_model}`:"Embeddings: lexical fallback";$("#embeddingBadge").classList.toggle("ready",!!d.embedding_model);$("#intelligenceStatusTitle").textContent="Local intelligence ready";$("#intelligenceStatusText").textContent=`${(d.installed_chat_models||[]).length} chat model(s) available for routing · no model inventory changes`;await refreshMemoryList()}catch(err){$("#intelligenceStatusTitle").textContent="Intelligence status unavailable";$("#intelligenceStatusText").textContent=err.message}}
async function refreshMemoryList(){try{const r=await api("/api/memory?limit=30"),d=await r.json(),box=$("#memoryList");box.innerHTML="";for(const m of d.memories||[]){const el=document.createElement("div");el.className="memory-item";el.innerHTML=`<div class="memory-item-head"><b>${escapeHtml(m.category||"memory")}</b><span>${escapeHtml(m.source||"local")}</span></div><p>${escapeHtml(m.content||"")}</p>`;box.appendChild(el)}if(!(d.memories||[]).length)box.innerHTML='<div class="memory-item"><p>No local memories yet. Say “remember that …” or add one above.</p></div>'}catch{}}
async function addManualMemory(){const input=$("#manualMemoryInput"),content=input.value.trim();if(!content)return;try{const r=await api("/api/memory",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({content,category:"manual"})});if(!r.ok)throw new Error(await r.text());input.value="";toast("Remembered locally","success");await refreshIntelligenceStatus()}catch(err){toast(err.message,"error")}}

function wireUI(){
  $("#authForm").addEventListener("submit",submitAuth);$("#loginTab").onclick=()=>setAuthMode("login");$("#signupTab").onclick=()=>setAuthMode("signup");
  $("#newChatBtn").onclick=newConversation;$("#menuBtn").onclick=()=>$("#sidebar").classList.add("open");$("#closeSidebar").onclick=()=>$("#sidebar").classList.remove("open");$("#chatSearch").addEventListener("input",e=>refreshConversations(e.target.value.trim()));$("#modelSelect").addEventListener("change",e=>localStorage.setItem("apexLastModel",e.target.value));
  $("#messageInput").addEventListener("input",autoResize);$("#messageInput").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey&&prefs.enterToSend){e.preventDefault();sendMessage()}});
  $("#sendBtn").onclick=()=>sendMessage();$("#stopBtn").onclick=stopGeneration;$("#chatModeBtn").onclick=()=>setAppMode("chat");$("#imageModeBtn").onclick=()=>setAppMode("image");$("#modelManagerBtn").onclick=()=>openModal("modelModal");$("#settingsBtn").onclick=()=>openSettings("general");$("#intelligenceBadge").onclick=()=>openSettings("intelligence");$("#exportCurrentBtn").onclick=()=>currentConversationId?exportConversation(currentConversationId):toast("Open a chat first");$("#plusMenuBtn").onclick=e=>openAnchoredMenu($("#plusMenu"),e.currentTarget,"above");$("#profileBtn").onclick=e=>openAnchoredMenu($("#profileMenu"),e.currentTarget,"above");
  $("#visualizerBtn").onclick=()=>{const modes=["aurora","particles","stars","mesh","waves","bubbles","matrix"];prefs.backgroundMode=modes[(modes.indexOf(prefs.backgroundMode)+1)%modes.length];applyPrefs();toast(`Background: ${prefs.backgroundMode}`)};
  $$("[data-close]").forEach(b=>b.onclick=()=>closeModal(b.dataset.close));
  $$("[data-plus-action]").forEach(b=>b.onclick=()=>{const a=b.dataset.plusAction;closeFloatingMenus();if(a==="image")setAppMode("image");if(a==="new")newConversation();if(a==="models")openModal("modelModal");if(a==="settings")openSettings("general")});
  $$("[data-profile-action]").forEach(b=>b.onclick=()=>{const a=b.dataset.profileAction;closeFloatingMenus();if(a==="settings")openSettings("general");if(a==="export")exportAll()});$("#logoutBtn").onclick=async()=>{try{await api("/api/auth/logout",{method:"POST"})}catch{}logoutLocal()};
  $$("[data-chat-action]").forEach(b=>b.onclick=async()=>{const action=b.dataset.chatAction,c=chatMenuConversation;closeFloatingMenus();if(!c)return;if(action==="pin")await updateConversation(c.id,{pinned:!Boolean(Number(c.pinned))});if(action==="rename")showRename(c);if(action==="export")exportConversation(c.id);if(action==="delete"&&confirm(`Delete "${c.title}"?`)){await deleteConversation(c.id);toast("Chat deleted","success")}});
  $("#renameSaveBtn").onclick=saveRename;$("#renameInput").addEventListener("keydown",e=>{if(e.key==="Enter")saveRename()});
  $$("#settingsNav button").forEach(b=>b.onclick=()=>switchSettingsTab(b.dataset.settingsTab));
  $$("#themeGrid button").forEach(b=>b.onclick=()=>{prefs.theme=b.dataset.themeChoice;fillSettingsForm();applyPrefs()});
  $$("#accentGrid button").forEach(b=>b.onclick=()=>{prefs.accent=b.dataset.accentChoice;fillSettingsForm();applyPrefs()});
  $$("#backgroundModes button").forEach(b=>b.onclick=()=>{prefs.backgroundMode=b.dataset.bgMode;fillSettingsForm();applyPrefs()});
  $$("#densityControl button").forEach(b=>b.onclick=()=>{prefs.density=b.dataset.density;fillSettingsForm();applyPrefs()});
  $$("#responseMode button").forEach(b=>b.onclick=()=>{prefs.responseMode=b.dataset.mode;fillSettingsForm();updateModeHint()});
  $$("#intelligenceModeControl button").forEach(b=>b.onclick=()=>{prefs.intelligenceMode=b.dataset.intelligenceMode;fillSettingsForm();updateIntelligenceBadge()});
  $$("#imageStepsControl button").forEach(b=>b.onclick=()=>{prefs.imageSteps=Number(b.dataset.imageSteps);fillSettingsForm()});
  $("#fontSize").oninput=e=>{$("#fontSizeValue").textContent=e.target.value;document.documentElement.style.setProperty("--font-size",`${e.target.value}px`)};
  $("#chatWidth").oninput=e=>{$("#chatWidthValue").textContent=e.target.value;document.documentElement.style.setProperty("--chat-width",`${e.target.value}px`)};
  $("#glassStrength").oninput=e=>{$("#glassStrengthValue").textContent=e.target.value;document.documentElement.style.setProperty("--glass-opacity",String(Number(e.target.value)/100))};
  $("#backgroundIntensity").oninput=e=>{$("#backgroundIntensityValue").textContent=e.target.value;if(visualEngine)visualEngine.setIntensity(Number(e.target.value)/100)};
  $("#backgroundSpeed").oninput=e=>{$("#backgroundSpeedValue").textContent=e.target.value;if(visualEngine)visualEngine.setSpeed(Number(e.target.value)/100)};
  $("#backgroundBlur").oninput=e=>{$("#backgroundBlurValue").textContent=e.target.value;document.documentElement.style.setProperty("--glass-blur",`${e.target.value}px`);if(visualEngine)visualEngine.setBlur(Number(e.target.value))};
  $("#temperature").oninput=e=>$("#temperatureValue").textContent=Number(e.target.value).toFixed(2);$("#maxTokens").oninput=e=>$("#maxTokensValue").textContent=e.target.value;
  $("#knowledgeResults").oninput=e=>$("#knowledgeResultsValue").textContent=e.target.value;$("#maxAutoModelB").oninput=e=>$("#maxAutoModelBValue").textContent=e.target.value;$("#memoryResults").oninput=e=>$("#memoryResultsValue").textContent=e.target.value;$("#addMemoryBtn").onclick=addManualMemory;$("#manualMemoryInput").addEventListener("keydown",e=>{if(e.key==="Enter")addManualMemory()});$("#knowledgeTestBtn").onclick=testKnowledgeSearch;$("#knowledgeTestQuery").addEventListener("keydown",e=>{if(e.key==="Enter")testKnowledgeSearch()});
  $("#saveSettings").onclick=async()=>{try{await saveSettings()}catch(err){toast(err.message,"error")}};
  $("#exportAllBtn").onclick=exportAll;$("#importAllBtn").onclick=()=>$("#importFile").click();$("#importFile").onchange=async e=>{const file=e.target.files[0];if(!file)return;try{const data=JSON.parse(await file.text()),r=await api("/api/import",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({data})}),d=await r.json();if(!r.ok)throw new Error(d.detail||"Import failed");toast(`Imported ${d.imported} chats`,"success");await refreshConversations()}catch(err){toast(err.message,"error")}e.target.value=""};
  $("#clearChatsBtn").onclick=async()=>{if(!confirm("Delete ALL chats for this account? This cannot be undone."))return;await api("/api/conversations",{method:"DELETE"});currentConversationId=null;currentConversation=null;$("#messages").innerHTML="";$("#emptyState").style.display="";await refreshConversations();toast("All chats cleared","success")};
  $$(".recommended-models button").forEach(b=>b.onclick=()=>$("#modelNameInput").value=b.dataset.model);$("#installModelBtn").onclick=installModel;
  document.addEventListener("click",e=>{if(!e.target.closest(".floating-menu")&&!e.target.closest("#plusMenuBtn")&&!e.target.closest("#profileBtn")&&!e.target.closest(".conversation-more"))closeFloatingMenus()});
  document.addEventListener("mousemove",e=>{const g=$("#cursorGlow");g.style.left=e.clientX+"px";g.style.top=e.clientY+"px"},{passive:true});
  document.addEventListener("keydown",e=>{const mod=e.ctrlKey||e.metaKey;if(mod&&e.key.toLowerCase()==="k"){e.preventDefault();$("#chatSearch").focus();$("#chatSearch").select()}if(mod&&e.key.toLowerCase()==="n"){e.preventDefault();newConversation()}if(mod&&e.key===","){e.preventDefault();openSettings("general")}if(e.key==="Escape"){if(isStreaming)stopGeneration();closeFloatingMenus();$$(".modal:not(.hidden)").forEach(m=>m.classList.add("hidden"))}});
  bindRipples()
}

visualEngine=new ApexVisualEngine($("#animatedBackground"));
bindSuggestions();wireUI();setAppMode("chat");setInterval(checkHealth,30000);

(async function init(){
  await loadConfig();
  applyPrefs();
  if(token){
    try{const r=await api("/api/me");if(!r.ok)throw new Error();const me=await r.json();username=me.username;await afterLogin()}catch{logoutLocal()}
  }
})();
