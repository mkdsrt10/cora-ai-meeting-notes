// The Cora tour: a short screenshot carousel of the main features. Shown once
// (setting tour_seen) right after onboarding, and on the first start of a
// version that has it for anyone who onboarded earlier; replayable from
// Settings > Preferences. Closing it (Done, Skip, Escape) sends one
// tour_closed {slide, slides, outcome} Usage event.
// Classic script sharing global scope with the other files in index.html
// (needs $, api and track).

const TOUR_SLIDES = [
  { img: '/tour/new-note.png', title: 'Start a note any time',
    body: 'Click New note (or press ⌘N) to record any meeting, even one in person. Type your own notes while Cora listens.' },
  { img: '/tour/call-prompt.png', title: 'Cora spots your calls', wide: true,
    body: 'Join a Google Meet, Zoom, Teams or Slack huddle and Cora offers to record it. Closing the window keeps Cora in the menu bar, still watching; quit it from the menu bar icon.' },
  { img: '/tour/notes.png', title: 'Notes written for you',
    body: 'After the call Cora writes the summary, decisions and action items. Raw Notes shows what you typed. Rate the notes or Export them as Markdown from here.' },
  { img: '/tour/beta-settings.png', title: 'Help shape the beta',
    body: 'Settings > Beta shows the name the Cora team sees you as, and is where you send feedback.' },
];

let tourIndex = 0;
let tourOpen = false;

function renderTourSlide(){
  const slide = TOUR_SLIDES[tourIndex];
  const img = $('#tourImage');
  img.src = slide.img;
  img.alt = slide.title;
  img.classList.toggle('tour-image-small', !!slide.wide);
  $('#tourTitle').textContent = slide.title;
  $('#tourBody').textContent = slide.body;
  $('#tourStep').textContent = `${tourIndex + 1} of ${TOUR_SLIDES.length}`;
  $('#tourBack').hidden = tourIndex === 0;
  const last = tourIndex === TOUR_SLIDES.length - 1;
  $('#tourNext').textContent = last ? 'Done' : 'Next';
  $('#tourSkip').hidden = last;
  $('#tourDots').innerHTML = TOUR_SLIDES.map((_, i) => `<span class="tour-dot${i === tourIndex ? ' active' : ''}"></span>`).join('');
}

function openTour(){
  tourIndex = 0;
  tourOpen = true;
  renderTourSlide();
  $('#tourOverlay').hidden = false;
  $('#tourNext').focus();
}

async function closeTour(outcome){
  if(!tourOpen) return;
  tourOpen = false;
  $('#tourOverlay').hidden = true;
  track('tour_closed', { slide: tourIndex + 1, slides: TOUR_SLIDES.length, outcome });
  try{ await api('/api/settings', { method: 'POST', body: JSON.stringify({ key: 'tour_seen', value: true }) }); }
  catch(error){ console.warn('[tour] tour_seen not saved:', error?.message); }
}

// Once per Install: after onboarding, or at the first start that has the tour.
async function maybeShowTour(){
  try{
    const { value } = await api('/api/settings?key=tour_seen');
    if(!value) openTour();
  }catch(error){ console.warn('[tour] not shown:', error?.message); }
}

$('#tourNext')?.addEventListener('click', () => {
  if(tourIndex === TOUR_SLIDES.length - 1){ closeTour('done'); return; }
  tourIndex += 1;
  renderTourSlide();
});
$('#tourBack')?.addEventListener('click', () => { if(tourIndex > 0){ tourIndex -= 1; renderTourSlide(); } });
$('#tourSkip')?.addEventListener('click', () => closeTour('skip'));
$('#settingsTakeTour')?.addEventListener('click', () => openTour());
window.addEventListener('keydown', (e) => {
  if(!tourOpen) return;
  if(e.key === 'Escape'){ e.preventDefault(); closeTour('skip'); }
  else if(e.key === 'ArrowRight'){ e.preventDefault(); $('#tourNext').click(); }
  else if(e.key === 'ArrowLeft'){ e.preventDefault(); $('#tourBack').click(); }
});
