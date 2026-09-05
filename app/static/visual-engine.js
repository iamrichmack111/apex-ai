class ApexVisualEngine {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d", {alpha:true});
    this.mode = "aurora";
    this.intensity = .65;
    this.speed = 1;
    this.blur = 18;
    this.running = true;
    this.time = 0;
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.mouse = {x:.5,y:.5};
    this.particles = [];
    this.stars = [];
    this.bubbles = [];
    this.matrixCols = [];
    this.resize();
    this.seed();
    window.addEventListener("resize",()=>this.resize());
    window.addEventListener("mousemove",e=>{
      this.mouse.x=e.clientX/window.innerWidth;
      this.mouse.y=e.clientY/window.innerHeight;
    },{passive:true});
    this.animate=this.animate.bind(this);
    requestAnimationFrame(this.animate);
  }

  resize() {
    const w=window.innerWidth,h=window.innerHeight;
    this.canvas.width=Math.floor(w*this.dpr);
    this.canvas.height=Math.floor(h*this.dpr);
    this.canvas.style.width=w+"px";
    this.canvas.style.height=h+"px";
    this.ctx.setTransform(this.dpr,0,0,this.dpr,0,0);
    this.w=w;this.h=h;
    this.seed();
  }

  seed() {
    const count=Math.max(35,Math.floor((this.w*this.h)/26000));
    this.particles=Array.from({length:count},()=>({
      x:Math.random()*this.w,y:Math.random()*this.h,
      vx:(Math.random()-.5)*.22,vy:(Math.random()-.5)*.22,
      r:Math.random()*1.8+.6,phase:Math.random()*Math.PI*2
    }));
    this.stars=Array.from({length:Math.max(90,count*3)},()=>({
      x:Math.random()*this.w,y:Math.random()*this.h,
      z:Math.random(),tw:Math.random()*Math.PI*2
    }));
    this.bubbles=Array.from({length:18},()=>({
      x:Math.random()*this.w,y:Math.random()*this.h,
      r:30+Math.random()*100,vy:.08+Math.random()*.22,
      drift:Math.random()*Math.PI*2
    }));
    const font=16;
    this.matrixCols=Array.from({length:Math.ceil(this.w/font)},()=>Math.random()*this.h/font);
  }

  colors() {
    const style=getComputedStyle(document.documentElement);
    const accent=style.getPropertyValue("--accent").trim()||"#8b5cf6";
    const strong=style.getPropertyValue("--accent-strong").trim()||"#22d3ee";
    const bg=style.getPropertyValue("--bg").trim()||"#101014";
    return {accent,strong,bg};
  }

  hexToRgb(hex) {
    const v=hex.replace("#","").trim();
    if(v.length!==6)return {r:139,g:92,b:246};
    return {r:parseInt(v.slice(0,2),16),g:parseInt(v.slice(2,4),16),b:parseInt(v.slice(4,6),16)};
  }

  rgba(hex,a) {
    const c=this.hexToRgb(hex);
    return `rgba(${c.r},${c.g},${c.b},${a})`;
  }

  setMode(mode){this.mode=mode||"aurora";}
  setIntensity(v){this.intensity=Math.max(0,Math.min(1,Number(v)||0));}
  setSpeed(v){this.speed=Math.max(.1,Math.min(3,Number(v)||1));}
  setBlur(v){this.blur=Math.max(0,Math.min(50,Number(v)||0));}

  clear(){
    this.ctx.clearRect(0,0,this.w,this.h);
  }

  drawAurora(c){
    const ctx=this.ctx,t=this.time*.00055*this.speed;
    ctx.save();
    ctx.globalCompositeOperation="screen";
    for(let layer=0;layer<5;layer++){
      const baseY=this.h*(.18+layer*.12);
      const grad=ctx.createLinearGradient(0,0,this.w,0);
      grad.addColorStop(0,this.rgba(layer%2?c.strong:c.accent,0));
      grad.addColorStop(.25,this.rgba(layer%2?c.accent:c.strong,.13*this.intensity));
      grad.addColorStop(.55,this.rgba(layer%2?c.strong:c.accent,.25*this.intensity));
      grad.addColorStop(1,this.rgba(c.accent,0));
      ctx.fillStyle=grad;
      ctx.beginPath();
      ctx.moveTo(0,this.h);
      for(let x=0;x<=this.w;x+=26){
        const y=baseY
          +Math.sin(x*.007+t*(1+layer*.08)+layer)*55
          +Math.sin(x*.003-t*.7+layer*1.8)*38
          +(this.mouse.y-.5)*45;
        ctx.lineTo(x,y);
      }
      ctx.lineTo(this.w,this.h);
      ctx.closePath();
      ctx.filter=`blur(${18+this.blur}px)`;
      ctx.fill();
    }
    ctx.restore();
  }

  drawParticles(c){
    const ctx=this.ctx, pts=this.particles, t=this.time*.001*this.speed;
    ctx.save();
    for(const p of pts){
      p.x+=p.vx*this.speed*2;p.y+=p.vy*this.speed*2;
      if(p.x<0)p.x=this.w;if(p.x>this.w)p.x=0;if(p.y<0)p.y=this.h;if(p.y>this.h)p.y=0;
    }
    for(let i=0;i<pts.length;i++){
      for(let j=i+1;j<pts.length;j++){
        const a=pts[i],b=pts[j],dx=a.x-b.x,dy=a.y-b.y,d=Math.hypot(dx,dy);
        if(d<125){
          ctx.strokeStyle=this.rgba(c.accent,(1-d/125)*.08*this.intensity);
          ctx.lineWidth=.7;
          ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
        }
      }
    }
    for(const p of pts){
      const pulse=.5+.5*Math.sin(t+p.phase);
      ctx.fillStyle=this.rgba(c.strong,(.2+.5*pulse)*this.intensity);
      ctx.beginPath();ctx.arc(p.x,p.y,p.r*(1+pulse*.5),0,Math.PI*2);ctx.fill();
    }
    ctx.restore();
  }

  drawStars(c){
    const ctx=this.ctx,t=this.time*.00015*this.speed,cx=this.w/2,cy=this.h/2;
    ctx.save();
    for(const s of this.stars){
      s.z+=.00035*this.speed;
      if(s.z>1){s.z=0;s.x=Math.random()*this.w;s.y=Math.random()*this.h;}
      const scale=.35+s.z*1.8;
      const x=cx+(s.x-cx)*scale+(this.mouse.x-.5)*20*s.z;
      const y=cy+(s.y-cy)*scale+(this.mouse.y-.5)*20*s.z;
      const alpha=(.1+s.z*.8)*this.intensity*(.65+.35*Math.sin(t*15+s.tw));
      ctx.fillStyle=this.rgba(c.strong,alpha);
      ctx.beginPath();ctx.arc(x,y,.45+s.z*1.5,0,Math.PI*2);ctx.fill();
    }
    ctx.restore();
  }

  drawMesh(c){
    const ctx=this.ctx,t=this.time*.00032*this.speed;
    const points=[];
    const cols=5,rows=4;
    for(let y=0;y<rows;y++)for(let x=0;x<cols;x++){
      points.push({
        x:(x/(cols-1))*this.w+Math.sin(t*2+x+y)*45+(this.mouse.x-.5)*25,
        y:(y/(rows-1))*this.h+Math.cos(t*1.7+x*1.3-y)*40+(this.mouse.y-.5)*25
      });
    }
    ctx.save();
    ctx.globalCompositeOperation="screen";
    for(let i=0;i<points.length;i++){
      const p=points[i];
      const g=ctx.createRadialGradient(p.x,p.y,0,p.x,p.y,170);
      g.addColorStop(0,this.rgba(i%2?c.accent:c.strong,.13*this.intensity));
      g.addColorStop(1,this.rgba(c.accent,0));
      ctx.fillStyle=g;ctx.fillRect(p.x-170,p.y-170,340,340);
    }
    ctx.strokeStyle=this.rgba(c.strong,.045*this.intensity);ctx.lineWidth=1;
    for(let y=0;y<rows;y++)for(let x=0;x<cols;x++){
      const idx=y*cols+x,p=points[idx];
      if(x<cols-1){const q=points[idx+1];ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(q.x,q.y);ctx.stroke();}
      if(y<rows-1){const q=points[idx+cols];ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(q.x,q.y);ctx.stroke();}
    }
    ctx.restore();
  }

  drawMatrix(c){
    const ctx=this.ctx,font=15,chars="01<>[]{}APEX";
    ctx.save();
    ctx.font=`${font}px ui-monospace, monospace`;
    for(let i=0;i<this.matrixCols.length;i++){
      const y=this.matrixCols[i]*font;
      const ch=chars[Math.floor(Math.random()*chars.length)];
      ctx.fillStyle=this.rgba(c.strong,.18*this.intensity);
      ctx.fillText(ch,i*font,y);
      if(Math.random()>.985)this.matrixCols[i]=0;
      this.matrixCols[i]+=.25*this.speed;
      if(y>this.h)this.matrixCols[i]=0;
    }
    ctx.restore();
  }

  drawBubbles(c){
    const ctx=this.ctx,t=this.time*.0005*this.speed;
    ctx.save();
    for(const b of this.bubbles){
      b.y-=b.vy*this.speed;
      b.x+=Math.sin(t+b.drift)*.12*this.speed;
      if(b.y<-b.r){b.y=this.h+b.r;b.x=Math.random()*this.w;}
      const g=ctx.createRadialGradient(b.x-b.r*.3,b.y-b.r*.3,0,b.x,b.y,b.r);
      g.addColorStop(0,this.rgba(c.strong,.09*this.intensity));
      g.addColorStop(.6,this.rgba(c.accent,.035*this.intensity));
      g.addColorStop(1,this.rgba(c.accent,0));
      ctx.fillStyle=g;ctx.beginPath();ctx.arc(b.x,b.y,b.r,0,Math.PI*2);ctx.fill();
      ctx.strokeStyle=this.rgba(c.strong,.05*this.intensity);ctx.lineWidth=.7;ctx.stroke();
    }
    ctx.restore();
  }

  drawWaves(c){
    const ctx=this.ctx,t=this.time*.0008*this.speed;
    ctx.save();
    ctx.globalCompositeOperation="screen";
    for(let k=0;k<7;k++){
      ctx.beginPath();
      for(let x=0;x<=this.w;x+=18){
        const y=this.h*(.25+k*.08)+Math.sin(x*.009+t*(1+k*.04)+k)*28+Math.sin(x*.003-t*.6+k)*19;
        if(x===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
      }
      ctx.strokeStyle=this.rgba(k%2?c.accent:c.strong,(.025+k*.007)*this.intensity);
      ctx.lineWidth=1.4;
      ctx.shadowBlur=12;
      ctx.shadowColor=k%2?c.accent:c.strong;
      ctx.stroke();
    }
    ctx.restore();
  }

  animate(ts){
    if(!this.running){requestAnimationFrame(this.animate);return;}
    this.time=ts;
    this.clear();
    if(this.mode!=="off"&&this.intensity>0){
      const c=this.colors();
      if(this.mode==="aurora")this.drawAurora(c);
      if(this.mode==="particles")this.drawParticles(c);
      if(this.mode==="stars")this.drawStars(c);
      if(this.mode==="mesh")this.drawMesh(c);
      if(this.mode==="matrix")this.drawMatrix(c);
      if(this.mode==="bubbles")this.drawBubbles(c);
      if(this.mode==="waves")this.drawWaves(c);
    }
    requestAnimationFrame(this.animate);
  }
}

window.ApexVisualEngine=ApexVisualEngine;
