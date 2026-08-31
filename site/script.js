/* The two figures play when they arrive on screen, and again on request.
   Everything else on this page is static. */

const figures = [...document.querySelectorAll("[data-figure]")];

const play = (figure) => {
  figure.classList.remove("is-playing");
  void figure.offsetWidth; // Restart the CSS animations from the top.
  figure.classList.add("is-playing");
};

if (figures.length && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const figure = entry.target;
          if (entry.intersectionRatio >= 0.3 && !figure.dataset.seen) {
            figure.dataset.seen = "1";
            play(figure);
          } else if (entry.intersectionRatio === 0) {
            delete figure.dataset.seen;
          }
        });
      },
      { threshold: [0, 0.3] },
    );

    figures.forEach((figure) => observer.observe(figure));
  } else {
    figures.forEach(play);
  }
}

document.querySelectorAll("[data-replay]").forEach((button) => {
  button.addEventListener("click", () => play(document.getElementById(button.dataset.replay)));
});
