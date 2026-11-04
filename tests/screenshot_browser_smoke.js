async (page) => {
  const base='http://127.0.0.1:8768/src/intext/assets/';
  const check=(ok,name)=>{if(!ok)throw new Error(name);};
  await page.setViewportSize({width:460,height:312});
  await page.goto(base+'popup.html');
  const markdown=await page.evaluate(async()=>{
    const raw='# 标题\n\n- 第一项\n- 第二项\n\n| 方法 | 结果 |\n| --- | --- |\n| OCR | 42 |\n\n```cpp\nint x = 42;\n```\n\n公式 $x^2 + 1$\n\n$$\n\\sum_{i=1}^{n} i\n$$\n\n<script>window.executed=true</script>\n![hidden](https://example.invalid/tracker)\n[unsafe](javascript:alert(1))';
    let copied='';window.pywebview={api:{copy_text(text){copied=text;return Promise.resolve(true);}}};
    intext.apply({seq:10,source:'# Heading',result:raw,from:'英语',to:'简体中文',sourceLang:'en',resultLang:'zh',model:'vision',status:'未缓存'});
    document.getElementById('copy').click();await Promise.resolve();
    const result=document.getElementById('result');
    return {heading:!!result.querySelector('h1'), list:result.querySelectorAll('li').length===2,table:!!result.querySelector('table'),
      code:result.querySelector('pre code').textContent==='int x = 42;\n',math:result.querySelectorAll('.katex').length===2,
      noExecutableHtml:!window.executed && !result.querySelector('script, iframe, img, a[href]'),rawCopy:copied===raw,
      fits:document.body.scrollWidth===innerWidth};
  });Object.entries(markdown).forEach(([key,value])=>check(value,'Markdown '+key));
  await page.setViewportSize({width:480,height:600});await page.goto(base+'settings.html');
  const modes=await page.evaluate(()=>{
    window.saved=[];window.pywebview={api:{save(value){saved.push(value);return Promise.resolve({});}}};
    intextSettings.apply({model:'vision',source:'en',target:'zh',apiKey:'never-in-preview'});
    const input=document.querySelector('#shot-input'),display=document.querySelector('#shot-display');
    const defaults=input.value==='ocr' && display.value==='popup';
    input.value='image';input.dispatchEvent(new Event('change',{bubbles:true}));
    const image=intextSettings.body();
    display.value='overlay';display.dispatchEvent(new Event('change',{bubbles:true}));
    const overlay=intextSettings.body();
    const shot=document.querySelector('#hotkey-shot').getBoundingClientRect();
    const inputBounds=input.parentElement.getBoundingClientRect(),displayBounds=display.parentElement.getBoundingClientRect();
    const selectKey=document.querySelector('#hotkey-select').getBoundingClientRect();
    const optionEdge=document.querySelector('#target').parentElement.getBoundingClientRect().right;
    const previewEdge=document.querySelector('#preview-kind').parentElement.getBoundingClientRect().right;
    const previewBounds=document.querySelector('#preview-kind').parentElement.getBoundingClientRect();
    const textRight=el=>{const range=document.createRange();range.selectNodeContents(el);return range.getBoundingClientRect().right;};
    const hotkeyTextEdge=textRight(document.querySelector('#hotkey-select .keycap-keys'));
    const bodies=[];
    for(const method of ['ocr','image'])for(const view of ['popup','overlay']){
      input.value=method;display.value=view;input.dispatchEvent(new Event('change',{bubbles:true}));
      bodies.push({method,view,body:intextSettings.body()});
    }
    return {defaults,belowShortcut:inputBounds.top>=shot.bottom && displayBounds.top>=inputBounds.bottom,
      leftArrows:[...document.querySelectorAll('.choice:not(.combo) > .menu-btn')].every(button=>{
        const arrow=button.querySelector('svg').getBoundingClientRect(), text=button.querySelector('.menu-label').getBoundingClientRect();
        return arrow.right<=text.left;
      }),
      aligned:Math.abs(inputBounds.right-optionEdge)<1 && Math.abs(displayBounds.right-optionEdge)<1 && Math.abs(previewEdge-optionEdge)<1,
      columnAligned:[selectKey,shot,displayBounds,previewBounds].every(rect=>Math.abs(rect.left-inputBounds.left)<1 && Math.abs(rect.right-inputBounds.right)<1),
      textAligned:['target','shot-input','shot-display','preview-kind'].every(id=>Math.abs(textRight(document.getElementById(id).parentElement.querySelector('.menu-label'))-hotkeyTextEdge)<1),
      languageInset:['source','target'].every(id=>parseFloat(getComputedStyle(document.getElementById(id).parentElement.querySelector('.menu-btn')).paddingRight)>=14),
      imageContent:Array.isArray(image.messages[1].content) && image.messages[1].content[1].type==='image_url',
      overlayContract:overlay.messages[0].content.includes('exactly one nonempty text'),
      secretsAbsent:!JSON.stringify(overlay).includes('never-in-preview'),
      optionalFieldsAbsent:!('temperature' in overlay) && !('reasoning_effort' in overlay),
      savedModes:saved.at(-1).shotInput==='image' && saved.at(-1).shotDisplay==='overlay',bodies};
  });Object.entries(modes).forEach(([key,value])=>{if(key!=='bodies')check(value,'Modes '+key);});
  await page.goto(base+'shot-overlay.html');await page.setViewportSize({width:640,height:360});
  const overlay=await page.evaluate(async()=>{
    const image=document.createElement('canvas');image.width=600;image.height=240;
    const ctx=image.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,600,240);ctx.fillStyle='black';ctx.font='24px sans-serif';ctx.fillText('Original heading',30,50);ctx.fillText('Text in its original location',30,140);
    const calls=[];window.pywebview={api:new Proxy({},{get:(_,key)=>(...args)=>{calls.push([key,...args]);return Promise.resolve(true);}})};
    intextShot.apply({seq:3,width:600,height:240,image:image.toDataURL(),text:'原文标题\n文字留在原处',model:'vision',busy:false,
      blocks:[{text:'原文标题',left:4,top:9,width:50,height:16,fontSize:24,background:'white',color:'black'},
      {text:'文字留在原处',left:4,top:45,width:66,height:16,fontSize:24,background:'white',color:'black'}]});
    fit();
    const labels=document.querySelectorAll('.region'), first=labels[0].getBoundingClientRect(), box=document.querySelector('#canvas').getBoundingClientRect();
    const tools=['retry','copy','original'].map(id=>document.getElementById(id).getBoundingClientRect());
    const sameSize=tools.every(rect=>rect.width===tools[0].width && rect.height===tools[0].height);
    const iconOnly=document.querySelector('#original').textContent.trim()==='';
    document.querySelector('#original').click();const compare=!document.querySelector('#labels').hidden===false;
    const accessibleToggle=document.querySelector('#original').getAttribute('aria-label')==='查看译文';
    document.querySelector('#original').click();
    document.querySelector('#copy').click();intextShot.apply({seq:2,text:'stale'});
    const fresh=document.querySelectorAll('.region').length===2;
    document.querySelector('#close').click();
    return {positioned:Math.abs((first.left-box.left)/box.width-.04)<.01,
      fitted:[...labels].every(el=>el.scrollHeight<=el.clientHeight+1),compare,sameSize,iconOnly,accessibleToggle,
      copy:calls.some(c=>c[0]==='copy_text' && c[1]==='原文标题\n文字留在原处'),fresh,close:calls.some(c=>c[0]==='hide'),
      fits:document.body.scrollWidth===innerWidth};
  });Object.entries(overlay).forEach(([key,value])=>check(value,'Overlay '+key));
  return {markdown,modes,overlay};
}
