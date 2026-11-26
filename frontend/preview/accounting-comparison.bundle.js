var R=globalThis,N=R.ShadowRoot&&(R.ShadyCSS===void 0||R.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,ie=Symbol(),se=new WeakMap,O=class{constructor(e,t,s){if(this._$cssResult$=!0,s!==ie)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=e,this.t=t}get styleSheet(){let e=this.o,t=this.t;if(N&&e===void 0){let s=t!==void 0&&t.length===1;s&&(e=se.get(t)),e===void 0&&((this.o=e=new CSSStyleSheet).replaceSync(this.cssText),s&&se.set(t,e))}return e}toString(){return this.cssText}},re=r=>new O(typeof r=="string"?r:r+"",void 0,ie);var oe=(r,e)=>{if(N)r.adoptedStyleSheets=e.map(t=>t instanceof CSSStyleSheet?t:t.styleSheet);else for(let t of e){let s=document.createElement("style"),i=R.litNonce;i!==void 0&&s.setAttribute("nonce",i),s.textContent=t.cssText,r.appendChild(s)}},j=N?r=>r:r=>r instanceof CSSStyleSheet?(e=>{let t="";for(let s of e.cssRules)t+=s.cssText;return re(t)})(r):r;var{is:Se,defineProperty:Ee,getOwnPropertyDescriptor:we,getOwnPropertyNames:Ce,getOwnPropertySymbols:xe,getPrototypeOf:ke}=Object,L=globalThis,ne=L.trustedTypes,Pe=ne?ne.emptyScript:"",Te=L.reactiveElementPolyfillSupport,x=(r,e)=>r,I={toAttribute(r,e){switch(e){case Boolean:r=r?Pe:null;break;case Object:case Array:r=r==null?r:JSON.stringify(r)}return r},fromAttribute(r,e){let t=r;switch(e){case Boolean:t=r!==null;break;case Number:t=r===null?null:Number(r);break;case Object:case Array:try{t=JSON.parse(r)}catch{t=null}}return t}},le=(r,e)=>!Se(r,e),ae={attribute:!0,type:String,converter:I,reflect:!1,useDefault:!1,hasChanged:le};Symbol.metadata??=Symbol("metadata"),L.litPropertyMetadata??=new WeakMap;var g=class extends HTMLElement{static addInitializer(e){this._$Ei(),(this.l??=[]).push(e)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(e,t=ae){if(t.state&&(t.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(e)&&((t=Object.create(t)).wrapped=!0),this.elementProperties.set(e,t),!t.noAccessor){let s=Symbol(),i=this.getPropertyDescriptor(e,s,t);i!==void 0&&Ee(this.prototype,e,i)}}static getPropertyDescriptor(e,t,s){let{get:i,set:o}=we(this.prototype,e)??{get(){return this[t]},set(n){this[t]=n}};return{get:i,set(n){let p=i?.call(this);o?.call(this,n),this.requestUpdate(e,p,s)},configurable:!0,enumerable:!0}}static getPropertyOptions(e){return this.elementProperties.get(e)??ae}static _$Ei(){if(this.hasOwnProperty(x("elementProperties")))return;let e=ke(this);e.finalize(),e.l!==void 0&&(this.l=[...e.l]),this.elementProperties=new Map(e.elementProperties)}static finalize(){if(this.hasOwnProperty(x("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(x("properties"))){let t=this.properties,s=[...Ce(t),...xe(t)];for(let i of s)this.createProperty(i,t[i])}let e=this[Symbol.metadata];if(e!==null){let t=litPropertyMetadata.get(e);if(t!==void 0)for(let[s,i]of t)this.elementProperties.set(s,i)}this._$Eh=new Map;for(let[t,s]of this.elementProperties){let i=this._$Eu(t,s);i!==void 0&&this._$Eh.set(i,t)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(e){let t=[];if(Array.isArray(e)){let s=new Set(e.flat(1/0).reverse());for(let i of s)t.unshift(j(i))}else e!==void 0&&t.push(j(e));return t}static _$Eu(e,t){let s=t.attribute;return s===!1?void 0:typeof s=="string"?s:typeof e=="string"?e.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(e=>this.enableUpdating=e),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(e=>e(this))}addController(e){(this._$EO??=new Set).add(e),this.renderRoot!==void 0&&this.isConnected&&e.hostConnected?.()}removeController(e){this._$EO?.delete(e)}_$E_(){let e=new Map,t=this.constructor.elementProperties;for(let s of t.keys())this.hasOwnProperty(s)&&(e.set(s,this[s]),delete this[s]);e.size>0&&(this._$Ep=e)}createRenderRoot(){let e=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return oe(e,this.constructor.elementStyles),e}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(e=>e.hostConnected?.())}enableUpdating(e){}disconnectedCallback(){this._$EO?.forEach(e=>e.hostDisconnected?.())}attributeChangedCallback(e,t,s){this._$AK(e,s)}_$ET(e,t){let s=this.constructor.elementProperties.get(e),i=this.constructor._$Eu(e,s);if(i!==void 0&&s.reflect===!0){let o=(s.converter?.toAttribute!==void 0?s.converter:I).toAttribute(t,s.type);this._$Em=e,o==null?this.removeAttribute(i):this.setAttribute(i,o),this._$Em=null}}_$AK(e,t){let s=this.constructor,i=s._$Eh.get(e);if(i!==void 0&&this._$Em!==i){let o=s.getPropertyOptions(i),n=typeof o.converter=="function"?{fromAttribute:o.converter}:o.converter?.fromAttribute!==void 0?o.converter:I;this._$Em=i;let p=n.fromAttribute(t,o.type);this[i]=p??this._$Ej?.get(i)??p,this._$Em=null}}requestUpdate(e,t,s,i=!1,o){if(e!==void 0){let n=this.constructor;if(i===!1&&(o=this[e]),s??=n.getPropertyOptions(e),!((s.hasChanged??le)(o,t)||s.useDefault&&s.reflect&&o===this._$Ej?.get(e)&&!this.hasAttribute(n._$Eu(e,s))))return;this.C(e,t,s)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(e,t,{useDefault:s,reflect:i,wrapped:o},n){s&&!(this._$Ej??=new Map).has(e)&&(this._$Ej.set(e,n??t??this[e]),o!==!0||n!==void 0)||(this._$AL.has(e)||(this.hasUpdated||s||(t=void 0),this._$AL.set(e,t)),i===!0&&this._$Em!==e&&(this._$Eq??=new Set).add(e))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(t){Promise.reject(t)}let e=this.scheduleUpdate();return e!=null&&await e,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[i,o]of this._$Ep)this[i]=o;this._$Ep=void 0}let s=this.constructor.elementProperties;if(s.size>0)for(let[i,o]of s){let{wrapped:n}=o,p=this[i];n!==!0||this._$AL.has(i)||p===void 0||this.C(i,void 0,o,p)}}let e=!1,t=this._$AL;try{e=this.shouldUpdate(t),e?(this.willUpdate(t),this._$EO?.forEach(s=>s.hostUpdate?.()),this.update(t)):this._$EM()}catch(s){throw e=!1,this._$EM(),s}e&&this._$AE(t)}willUpdate(e){}_$AE(e){this._$EO?.forEach(t=>t.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(e)),this.updated(e)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(e){return!0}update(e){this._$Eq&&=this._$Eq.forEach(t=>this._$ET(t,this[t])),this._$EM()}updated(e){}firstUpdated(e){}};g.elementStyles=[],g.shadowRootOptions={mode:"open"},g[x("elementProperties")]=new Map,g[x("finalized")]=new Map,Te?.({ReactiveElement:g}),(L.reactiveElementVersions??=[]).push("2.1.2");var J=globalThis,he=r=>r,D=J.trustedTypes,ce=D?D.createPolicy("lit-html",{createHTML:r=>r}):void 0,ge="$lit$",f=`lit$${Math.random().toFixed(9).slice(2)}$`,fe="?"+f,Ue=`<${fe}>`,y=document,P=()=>y.createComment(""),T=r=>r===null||typeof r!="object"&&typeof r!="function",Y=Array.isArray,He=r=>Y(r)||typeof r?.[Symbol.iterator]=="function",z=`[ 	
\f\r]`,k=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,de=/-->/g,pe=/>/g,_=RegExp(`>|${z}(?:([^\\s"'>=/]+)(${z}*=${z}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),ue=/'/g,$e=/"/g,_e=/^(?:script|style|textarea|title)$/i,Z=r=>(e,...t)=>({_$litType$:r,strings:e,values:t}),m=Z(1),Ie=Z(2),ze=Z(3),A=Symbol.for("lit-noChange"),c=Symbol.for("lit-nothing"),me=new WeakMap,v=y.createTreeWalker(y,129);function ve(r,e){if(!Y(r)||!r.hasOwnProperty("raw"))throw Error("invalid template strings array");return ce!==void 0?ce.createHTML(e):e}var Me=(r,e)=>{let t=r.length-1,s=[],i,o=e===2?"<svg>":e===3?"<math>":"",n=k;for(let p=0;p<t;p++){let l=r[p],u,$,h=-1,a=0;for(;a<l.length&&(n.lastIndex=a,$=n.exec(l),$!==null);)a=n.lastIndex,n===k?$[1]==="!--"?n=de:$[1]!==void 0?n=pe:$[2]!==void 0?(_e.test($[2])&&(i=RegExp("</"+$[2],"g")),n=_):$[3]!==void 0&&(n=_):n===_?$[0]===">"?(n=i??k,h=-1):$[1]===void 0?h=-2:(h=n.lastIndex-$[2].length,u=$[1],n=$[3]===void 0?_:$[3]==='"'?$e:ue):n===$e||n===ue?n=_:n===de||n===pe?n=k:(n=_,i=void 0);let d=n===_&&r[p+1].startsWith("/>")?" ":"";o+=n===k?l+Ue:h>=0?(s.push(u),l.slice(0,h)+ge+l.slice(h)+f+d):l+f+(h===-2?p:d)}return[ve(r,o+(r[t]||"<?>")+(e===2?"</svg>":e===3?"</math>":"")),s]},U=class r{constructor({strings:e,_$litType$:t},s){let i;this.parts=[];let o=0,n=0,p=e.length-1,l=this.parts,[u,$]=Me(e,t);if(this.el=r.createElement(u,s),v.currentNode=this.el.content,t===2||t===3){let h=this.el.content.firstChild;h.replaceWith(...h.childNodes)}for(;(i=v.nextNode())!==null&&l.length<p;){if(i.nodeType===1){if(i.hasAttributes())for(let h of i.getAttributeNames())if(h.endsWith(ge)){let a=$[n++],d=i.getAttribute(h).split(f),M=/([.?@])?(.*)/.exec(a);l.push({type:1,index:o,name:M[2],strings:d,ctor:M[1]==="."?q:M[1]==="?"?G:M[1]==="@"?K:E}),i.removeAttribute(h)}else h.startsWith(f)&&(l.push({type:6,index:o}),i.removeAttribute(h));if(_e.test(i.tagName)){let h=i.textContent.split(f),a=h.length-1;if(a>0){i.textContent=D?D.emptyScript:"";for(let d=0;d<a;d++)i.append(h[d],P()),v.nextNode(),l.push({type:2,index:++o});i.append(h[a],P())}}}else if(i.nodeType===8)if(i.data===fe)l.push({type:2,index:o});else{let h=-1;for(;(h=i.data.indexOf(f,h+1))!==-1;)l.push({type:7,index:o}),h+=f.length-1}o++}}static createElement(e,t){let s=y.createElement("template");return s.innerHTML=e,s}};function S(r,e,t=r,s){if(e===A)return e;let i=s!==void 0?t._$Co?.[s]:t._$Cl,o=T(e)?void 0:e._$litDirective$;return i?.constructor!==o&&(i?._$AO?.(!1),o===void 0?i=void 0:(i=new o(r),i._$AT(r,t,s)),s!==void 0?(t._$Co??=[])[s]=i:t._$Cl=i),i!==void 0&&(e=S(r,i._$AS(r,e.values),i,s)),e}var V=class{constructor(e,t){this._$AV=[],this._$AN=void 0,this._$AD=e,this._$AM=t}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(e){let{el:{content:t},parts:s}=this._$AD,i=(e?.creationScope??y).importNode(t,!0);v.currentNode=i;let o=v.nextNode(),n=0,p=0,l=s[0];for(;l!==void 0;){if(n===l.index){let u;l.type===2?u=new H(o,o.nextSibling,this,e):l.type===1?u=new l.ctor(o,l.name,l.strings,this,e):l.type===6&&(u=new F(o,this,e)),this._$AV.push(u),l=s[++p]}n!==l?.index&&(o=v.nextNode(),n++)}return v.currentNode=y,i}p(e){let t=0;for(let s of this._$AV)s!==void 0&&(s.strings!==void 0?(s._$AI(e,s,t),t+=s.strings.length-2):s._$AI(e[t])),t++}},H=class r{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(e,t,s,i){this.type=2,this._$AH=c,this._$AN=void 0,this._$AA=e,this._$AB=t,this._$AM=s,this.options=i,this._$Cv=i?.isConnected??!0}get parentNode(){let e=this._$AA.parentNode,t=this._$AM;return t!==void 0&&e?.nodeType===11&&(e=t.parentNode),e}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(e,t=this){e=S(this,e,t),T(e)?e===c||e==null||e===""?(this._$AH!==c&&this._$AR(),this._$AH=c):e!==this._$AH&&e!==A&&this._(e):e._$litType$!==void 0?this.$(e):e.nodeType!==void 0?this.T(e):He(e)?this.k(e):this._(e)}O(e){return this._$AA.parentNode.insertBefore(e,this._$AB)}T(e){this._$AH!==e&&(this._$AR(),this._$AH=this.O(e))}_(e){this._$AH!==c&&T(this._$AH)?this._$AA.nextSibling.data=e:this.T(y.createTextNode(e)),this._$AH=e}$(e){let{values:t,_$litType$:s}=e,i=typeof s=="number"?this._$AC(e):(s.el===void 0&&(s.el=U.createElement(ve(s.h,s.h[0]),this.options)),s);if(this._$AH?._$AD===i)this._$AH.p(t);else{let o=new V(i,this),n=o.u(this.options);o.p(t),this.T(n),this._$AH=o}}_$AC(e){let t=me.get(e.strings);return t===void 0&&me.set(e.strings,t=new U(e)),t}k(e){Y(this._$AH)||(this._$AH=[],this._$AR());let t=this._$AH,s,i=0;for(let o of e)i===t.length?t.push(s=new r(this.O(P()),this.O(P()),this,this.options)):s=t[i],s._$AI(o),i++;i<t.length&&(this._$AR(s&&s._$AB.nextSibling,i),t.length=i)}_$AR(e=this._$AA.nextSibling,t){for(this._$AP?.(!1,!0,t);e!==this._$AB;){let s=he(e).nextSibling;he(e).remove(),e=s}}setConnected(e){this._$AM===void 0&&(this._$Cv=e,this._$AP?.(e))}},E=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(e,t,s,i,o){this.type=1,this._$AH=c,this._$AN=void 0,this.element=e,this.name=t,this._$AM=i,this.options=o,s.length>2||s[0]!==""||s[1]!==""?(this._$AH=Array(s.length-1).fill(new String),this.strings=s):this._$AH=c}_$AI(e,t=this,s,i){let o=this.strings,n=!1;if(o===void 0)e=S(this,e,t,0),n=!T(e)||e!==this._$AH&&e!==A,n&&(this._$AH=e);else{let p=e,l,u;for(e=o[0],l=0;l<o.length-1;l++)u=S(this,p[s+l],t,l),u===A&&(u=this._$AH[l]),n||=!T(u)||u!==this._$AH[l],u===c?e=c:e!==c&&(e+=(u??"")+o[l+1]),this._$AH[l]=u}n&&!i&&this.j(e)}j(e){e===c?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,e??"")}},q=class extends E{constructor(){super(...arguments),this.type=3}j(e){this.element[this.name]=e===c?void 0:e}},G=class extends E{constructor(){super(...arguments),this.type=4}j(e){this.element.toggleAttribute(this.name,!!e&&e!==c)}},K=class extends E{constructor(e,t,s,i,o){super(e,t,s,i,o),this.type=5}_$AI(e,t=this){if((e=S(this,e,t,0)??c)===A)return;let s=this._$AH,i=e===c&&s!==c||e.capture!==s.capture||e.once!==s.once||e.passive!==s.passive,o=e!==c&&(s===c||i);i&&this.element.removeEventListener(this.name,this,s),o&&this.element.addEventListener(this.name,this,e),this._$AH=e}handleEvent(e){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,e):this._$AH.handleEvent(e)}},F=class{constructor(e,t,s){this.element=e,this.type=6,this._$AN=void 0,this._$AM=t,this.options=s}get _$AU(){return this._$AM._$AU}_$AI(e){S(this,e)}};var Re=J.litHtmlPolyfillSupport;Re?.(U,H),(J.litHtmlVersions??=[]).push("3.3.3");var B=(r,e,t)=>{let s=t?.renderBefore??e,i=s._$litPart$;if(i===void 0){let o=t?.renderBefore??null;s._$litPart$=i=new H(e.insertBefore(P(),o),o,void 0,t??{})}return i._$AI(r),i};var Q=globalThis,w=class extends g{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let e=super.createRenderRoot();return this.renderOptions.renderBefore??=e.firstChild,e}update(e){let t=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(e),this._$Do=B(t,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return A}};w._$litElement$=!0,w.finalized=!0,Q.litElementHydrateSupport?.({LitElement:w});var Oe=Q.litElementPolyfillSupport;Oe?.({LitElement:w});(Q.litElementVersions??=[]).push("4.2.2");var ye={mixed:{label:"Solar + battery + grid",description:"Example session \xB7 a complete source breakdown",amounts:{solar:18.35,battery:5.65,grid:4.23,unknown:0},gridCost:1.27},actual:{label:"Your last session \xB7 sources unavailable",description:"Your last session \xB7 28.233 kWh recorded, sources not identified",amounts:{solar:0,battery:0,grid:0,unknown:28.233},gridCost:0},partial:{label:"Partly identified",description:"Example session \xB7 some intervals could not be assigned to a source",amounts:{solar:16.2,battery:3.1,grid:2.73,unknown:6.2},gridCost:.82},solar:{label:"Solar only",description:"Example session \xB7 all charging energy attributed to direct solar",amounts:{solar:28.23,battery:0,grid:0,unknown:0},gridCost:0},small:{label:"Small grid share",description:"Example session \xB7 tiny shares keep their true proportions",amounts:{solar:28.18,battery:0,grid:.05,unknown:0},gridCost:.02},empty:{label:"Waiting for energy",description:"Example session \xB7 no energy recorded yet",amounts:{solar:0,battery:0,grid:0,unknown:0},gridCost:null}},Ne={solar:"Solar",battery:"Battery",grid:"Grid",unknown:"Not identified"},Ae=["solar","battery","grid","unknown"],X="mixed",ee="light",te=!1,b=r=>r.toLocaleString("en-GB",{maximumFractionDigits:2}),be=r=>r.toLocaleString("en-GB",{style:"currency",currency:"EUR"}),C=r=>r>0&&r<1?"<1%":`${Math.round(r)}%`;function W(){let r=ye[X],e=Ae.reduce((a,d)=>a+r.amounts[d],0),t=Ae.filter(a=>r.amounts[a]>0).map(a=>({source:a,label:Ne[a],kwh:r.amounts[a],share:r.amounts[a]/e*100})),s=r.amounts.unknown,i=e>0&&s===e,o=e?(e-s)/e*100:0,n=e?i?"Energy recorded. Its sources could not be identified.":s>0?`${b(s)} kWh could not be assigned to a source.`:null:"No energy recorded yet.",p=!e||i||r.gridCost===null?null:s>0?`${be(r.gridCost)} known grid cost`:`${be(r.gridCost)} grid cost`,l=(a=!1)=>t.length?m` <div
          class="split ${a?"thin":""}"
          role="img"
          aria-label=${t.map(d=>`${d.label}: ${b(d.kwh)} kWh, ${C(d.share)}`).join("; ")}
        >
          ${t.map(d=>m`<span
                class="segment ${d.source}"
                style=${`flex-basis:${d.share}%`}
                title=${`${d.label} \xB7 ${b(d.kwh)} kWh \xB7 ${C(d.share)}`}
              >
                ${!a&&d.share>=12?m`<b>${C(d.share)}</b>`:c}
              </span>`)}
        </div>`:c,u=()=>e?m`<details>
          <summary>About this breakdown</summary>
          <div class="detail-copy">
            <p>
              ${i?"Source information is unavailable for this session.":`Sources identified for ${C(o)} of the recorded energy.`}
            </p>
            ${r.amounts.battery>0?m`<p>
                  Battery means energy from your home battery. Its earlier solar or grid origin is
                  not tracked.
                </p>`:c}
            ${i||r.gridCost===null?m`<p>Grid cost is unavailable. This does not mean the session was free.</p>`:m`<p>
                  ${s>0?"The cost shown covers only the identified grid share.":"The cost shown covers grid electricity only."}
                  Battery storage costs are not included.
                </p>`}
            <p>
              The breakdown is estimated from site measurements. Grid draw is assigned to charging
              first; this rule does not control your charger.
            </p>
          </div>
        </details>`:c,$=()=>m`<div class="foot">
      ${n?m`<p class="explanation">${n}</p>`:c}
      <div class="foot-row">
        ${p?m`<span class="cost">${p}</span>`:c}${u()}
      </div>
    </div>`,h=()=>m`<div class="energy-heading">
      <h2>Charging energy</h2>
      ${e?m`<span class="total"><strong>${b(e)}</strong> kWh</span>`:c}
    </div>`;document.documentElement.dataset.theme=ee,B(m`
      <header class="page-heading">
        <a href="./">THOR / Design preview</a>
        <h1>Where did the energy come from?</h1>
        <p>Three compact alternatives for the session history.</p>
      </header>
      <section class="controls" aria-label="Preview controls">
        <label
          >Session<select
            aria-label="Session"
            .value=${X}
            @change=${a=>{X=a.target.value,W()}}
          >
            ${Object.entries(ye).map(([a,d])=>m`<option value=${a}>${d.label}</option>`)}
          </select></label
        >
        <label
          >Theme<select
            aria-label="Theme"
            .value=${ee}
            @change=${a=>{ee=a.target.value,W()}}
          >
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select></label
        >
        <label
          >Card width<select
            aria-label="Card width"
            .value=${te?"mobile":"wide"}
            @change=${a=>{te=a.target.value==="mobile",W()}}
          >
            <option value="wide">Responsive</option>
            <option value="mobile">Mobile · 360 px</option>
          </select></label
        >
      </section>
      <p class="scenario-description" aria-live="polite">${r.description}</p>
      <div class="variants ${te?"narrow":""}">
        <section class="variant">
          <div class="variant-heading">
            <span class="letter">A</span>
            <h3>Split bar + source values</h3>
            <span class="recommended">Recommended</span>
          </div>
          <article class="energy-card variant-a">
            ${h()}${l()}
            ${t.length?m`<div class="source-values">
                  ${t.map(a=>m`<div class="source-value">
                        <span class="source-label"><i class=${a.source}></i>${a.label}</span>
                        <strong>${b(a.kwh)} <small>kWh</small></strong>
                      </div>`)}
                </div>`:c}${$()}
          </article>
          <p class="variant-note">The mix at a glance, with easy-to-read amounts below.</p>
        </section>
        <section class="variant">
          <div class="variant-heading">
            <span class="letter">B</span>
            <h3>Compact energy strip</h3>
          </div>
          <article class="energy-card variant-b">
            ${h()}${l(!0)}
            ${t.length?m`<div class="inline-values">
                  ${t.map(a=>m`<div class="inline-value">
                        <i class=${a.source}></i><span>${a.label}</span
                        ><strong>${b(a.kwh)} <small>kWh</small></strong
                        ><span class="share">${C(a.share)}</span>
                      </div>`)}
                </div>`:c}${$()}
          </article>
          <p class="variant-note">The smallest footprint; the labels carry more of the detail.</p>
        </section>
        <section class="variant">
          <div class="variant-heading">
            <span class="letter">C</span>
            <h3>Source rows</h3>
          </div>
          <article class="energy-card variant-c">
            ${h()}
            <div class="source-rows">
              ${t.map(a=>m`<div class="source-row">
                    <div class="row-heading">
                      <span class="source-label"><i class=${a.source}></i>${a.label}</span
                      ><span
                        ><strong>${b(a.kwh)} <small>kWh</small></strong
                        ><span class="share">${C(a.share)}</span></span
                      >
                    </div>
                    <div class="row-track">
                      <span class=${a.source} style=${`width:${a.share}%`}></span>
                    </div>
                  </div>`)}
            </div>
            ${$()}
          </article>
          <p class="variant-note">
            The clearest individual values, at the cost of a little more height.
          </p>
        </section>
      </div>
      <p class="preview-note">
        Comparison only · Example mixes are simulated · No changes to Home Assistant
      </p>
    `,document.querySelector("#comparison"))}W();
/*! Bundled license information:

@lit/reactive-element/css-tag.js:
  (**
   * @license
   * Copyright 2019 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/reactive-element.js:
lit-html/lit-html.js:
lit-element/lit-element.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/is-server.js:
  (**
   * @license
   * Copyright 2022 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)
*/
