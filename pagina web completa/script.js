// Scroll reveal: show elements as they enter the viewport
const observer = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  },
  { threshold: 0.14 }
);

document.querySelectorAll('.reveal').forEach((el) => observer.observe(el));

// Dynamic year in footer
document.getElementById('year').textContent = new Date().getFullYear();

// Header subtle transparency intensifies on scroll
const header = document.querySelector('.site-header');
let last = 0;
window.addEventListener('scroll', () => {
  const y = window.scrollY || document.documentElement.scrollTop;
  if (!header) return;
  if (y > 12 && last <= 12) {
    header.style.background = 'rgba(255,255,255,0.72)';
  } else if (y <= 12 && last > 12) {
    header.style.background = '';
  }
  last = y;
});

// Parallax layers in hero
const parallaxRoot = document.querySelector('.parallax');
if (parallaxRoot) {
  const layers = parallaxRoot.querySelectorAll('[data-depth]');
  window.addEventListener('mousemove', (e) => {
    const { innerWidth: w, innerHeight: h } = window;
    const x = (e.clientX - w / 2) / (w / 2);
    const y = (e.clientY - h / 2) / (h / 2);
    layers.forEach((layer) => {
      const depth = parseFloat(layer.getAttribute('data-depth') || '0');
      const translateX = -x * depth * 20;
      const translateY = -y * depth * 20;
      layer.style.transform = `translate3d(${translateX}px, ${translateY}px, 0)`;
    });
  });
}


