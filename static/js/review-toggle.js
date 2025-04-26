// static/js/review-toggle.js
document.addEventListener('DOMContentLoaded', () => {
  // Find all review buttons on the page
  const buttons = document.querySelectorAll('.review-btn');

  buttons.forEach(btn => {
    btn.addEventListener('click', async event => {
      event.preventDefault();  // Prevent any default form submissions

      const eventId = btn.dataset.event;
      // Determine current state from aria-pressed
      const isReviewed = btn.getAttribute('aria-pressed') === 'true';
      // We want to toggle, so reviewed → unreview (DELETE), unreview → review (POST)
      const method = isReviewed ? 'DELETE' : 'POST';
      const url = `/detections/${encodeURIComponent(eventId)}/review`;
      const fetchOptions = {
        method: method,
        headers: { 'Content-Type': 'application/json' }
      };
      // Only include JSON body on POST
      if (!isReviewed) {
        fetchOptions.body = JSON.stringify({ reviewed: true });
      }

      try {
        const resp = await fetch(url, fetchOptions);
        if (!resp.ok) {
          console.error(`Failed to toggle review (status ${resp.status})`);
          return;
        }
        const json = await resp.json();
        // Update the button state based on the server's response
        const nowReviewed = json.reviewed === true;
        btn.setAttribute('aria-pressed', nowReviewed);
        // Swap icon class: bi-check for reviewed, bi-check-circle for unreviewed
        const icon = btn.querySelector('i');
        if (icon) {
          icon.classList.remove('bi-check', 'bi-check-circle');
          icon.classList.add(nowReviewed ? 'bi-check' : 'bi-check-circle');
        }
      } catch (err) {
        console.error('Error toggling review flag:', err);
      }
    });
  });
});

