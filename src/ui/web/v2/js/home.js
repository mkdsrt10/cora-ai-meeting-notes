// Home in the v2 shell: the meeting list. (T1: frame only; T3 fills it.)
// Classic script sharing global scope with the other v2 files.

definePage('home', {
  title: 'Home',
  async render(host){
    host.innerHTML = '<div class="page"><h1 class="ptitle">Home</h1><div class="empty"><strong>Your meetings show up here.</strong></div></div>';
  },
});
