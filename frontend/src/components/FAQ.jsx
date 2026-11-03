import { useId, useState } from 'react';
import { APP_NAME, container, focusRing, label } from './classes';

const FAQS = [
  { q: 'What kind of video works?', a: 'Most standard match recordings (for example MP4 or MOV from a phone, a camcorder or a streaming camera) work. Clearer, higher-resolution footage gives better results.' },
  { q: 'What camera angle is best?', a: 'A fixed, elevated, wide-angle view where the pitch lines are visible. The lines let us map players onto the field for accurate distance and speed. Broadcast-style footage with lots of zooming and cutting is harder to work with.' },
  { q: 'How accurate is the tracking?', a: 'In a recent test, Player Lock-On stayed on the selected player in 471 of 477 frames. Accuracy depends on video quality, camera angle and how crowded the play is. When we’re not sure who a player is, we say “Unknown player” rather than guess.' },
  { q: 'Can it read jersey numbers automatically?', a: 'Not reliably yet. Typical match footage is often too low-resolution to read numbers dependably, so you can assign names and numbers from your roster and correct any misread number.' },
  { q: 'Is my footage private?', a: 'Yes. Uploads are tied to your account and aren’t visible to other users.' },
  { q: 'Who owns my data?', a: 'You do. Your videos and the stats generated from them belong to you.' },
  { q: 'Is the injury risk score medical advice?', a: 'No. Roster Injury Risk (coming soon) is a planning aid based on published research factors such as playing surface, workload, fixture congestion and injury history. Always consult a qualified medical professional about injuries.' },
  { q: 'What data will the injury risk score use?', a: 'When it launches (coming soon), it will use match surface (turf or grass), recent workload, how close together matches are, and any past injuries a player chooses to enter, including the type of injury and how long it lasted.' },
  { q: 'How much does it cost?', a: `Pricing isn’t set yet. ${APP_NAME} is currently in development.` },
  { q: 'What devices can I use?', a: `${APP_NAME} runs in any modern web browser on desktop, tablet or phone. There’s nothing to install.` },
  { q: 'Do I need special cameras or wearables?', a: 'No. It works from video alone, with no GPS vests or sensors.' },
  { q: 'How long does processing take?', a: 'It depends on the length and resolution of the video. Shorter clips are ready fastest.' },
  { q: 'Can I compare matches played in different conditions?', a: 'Yes. Tag matches (for example rain) and the Insights page compares how players perform across them.' },
];

function FAQItem({ item, open, onToggle }) {
  const id = useId();
  return (
    <li className="border-b border-line">
      <h3>
        <button
          type="button"
          id={`${id}-btn`}
          aria-expanded={open}
          aria-controls={`${id}-panel`}
          onClick={onToggle}
          className={`flex w-full items-center justify-between gap-4 rounded py-5 text-left text-body font-semibold text-fg hover:text-fg-secondary ${focusRing}`}
        >
          {item.q}
          <span aria-hidden="true" className={`text-xl text-fg-muted transition-transform ${open ? 'rotate-45' : ''}`}>+</span>
        </button>
      </h3>
      <div id={`${id}-panel`} role="region" aria-labelledby={`${id}-btn`} hidden={!open} className="pb-5 text-body text-fg-secondary">
        {item.a}
      </div>
    </li>
  );
}

export default function FAQ() {
  const [openIndex, setOpenIndex] = useState(0);
  return (
    <section id="faq" aria-labelledby="faq-heading" className="scroll-mt-20 border-t border-line">
      <div className={`${container} py-20 sm:py-24`}>
        <div className="mx-auto max-w-3xl">
          <p className={label}>FAQ</p>
          <h2 id="faq-heading" className="mt-3 text-3xl font-bold tracking-tight text-fg sm:text-4xl">Frequently asked questions</h2>
          <ul className="mt-10 border-t border-line">
            {FAQS.map((item, i) => (
              <FAQItem key={item.q} item={item} open={openIndex === i} onToggle={() => setOpenIndex(openIndex === i ? -1 : i)} />
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
