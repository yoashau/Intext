/* Local rendering only: no raw HTML, network images or navigable model links. */
(() => {
  const md = window.markdownit({html:false, breaks:true, linkify:false, typographer:false});
  md.renderer.rules.image = (tokens, index) => md.utils.escapeHtml(tokens[index].content || '');
  md.renderer.rules.link_open = () => '<span class="md-link">';
  md.renderer.rules.link_close = () => '</span>';
  md.renderer.rules.table_open = () => '<div class="md-table"><table>';
  md.renderer.rules.table_close = () => '</table></div>';
  function math(content, display) {
    try { return window.katex.renderToString(content, {displayMode:display, throwOnError:false, trust:false, strict:'ignore', maxExpand:1000}); }
    catch (_) { return md.utils.escapeHtml(content); }
  }
  md.inline.ruler.before('escape', 'intext_math', (state, silent) => {
    const start=state.pos, src=state.src;
    const slash=src.startsWith('\\(',start), dollar=src[start]==='$' && src[start+1]!=='$';
    if(!slash && !dollar) return false;
    if(dollar && /\s/.test(src[start+1] || '')) return false;
    const opening=slash?'\\(':'$', closing=slash?'\\)':'$';
    let end=start+opening.length;
    while((end=src.indexOf(closing,end))>=0 && src[end-1]==='\\') end+=closing.length;
    if(end<0 || src.slice(start+opening.length,end).includes('\n')) return false;
    if(dollar && /\d/.test(src[end+1] || '')) return false;
    if(!silent){const token=state.push('intext_math','math',0);token.content=src.slice(start+opening.length,end);}
    state.pos=end+closing.length;return true;
  });
  md.renderer.rules.intext_math=(tokens,index)=>math(tokens[index].content,false);
  md.block.ruler.before('fence','intext_math_block',(state,start,end,silent)=>{
    const offset=state.bMarks[start]+state.tShift[start], line=state.src.slice(offset,state.eMarks[start]).trim();
    const opening=line.startsWith('$$')?'$$':line.startsWith('\\[')?'\\[':'';
    if(!opening)return false;
    const closing=opening==='$$'?'$$':'\\]';let content=line.slice(opening.length), next=start;
    let found=content.endsWith(closing);
    if(found)content=content.slice(0,-closing.length);
    else for(next=start+1;next<end;next++){
      const value=state.src.slice(state.bMarks[next]+state.tShift[next],state.eMarks[next]);
      if(value.trimEnd().endsWith(closing)){content+='\n'+value.trimEnd().slice(0,-closing.length);found=true;break;}
      content+='\n'+value;
    }
    if(!found)return false;
    if(!silent){const token=state.push('intext_math_block','math',0);token.block=true;token.content=content;token.map=[start,next+1];}
    state.line=next+1;return true;
  },{alt:['paragraph','reference','blockquote','list']});
  md.renderer.rules.intext_math_block=(tokens,index)=>'<div class="md-math">'+math(tokens[index].content,true)+'</div>\n';
  window.intextMarkdown={render(element,text){
    text=String(text || '');
    if(element.dataset.raw===text)return;
    element.dataset.raw=text;
    element.classList.add('markdown');
    // markdown-it escapes source HTML. Custom renderers add only fixed tags;
    // KaTeX runs with trust disabled and a bounded expansion count.
    element.innerHTML=md.render(text).trimEnd();
    for(const region of element.querySelectorAll('pre,.md-table,.md-math')) {
      region.tabIndex=0;
      region.setAttribute('role','region');
      region.setAttribute('aria-label',region.matches('pre')?'代码':region.classList.contains('md-table')?'表格':'公式');
    }
  }};
})();
