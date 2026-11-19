// The Advanced box (Simon, 2026-11-19): "add two check boxes to the advanced box in [Scenes] so that images and video
// AND text are separate unlocks. Then I want to match this look in images and videos ... remove the current
// 'advanced' (video) or 'unlocked extracted images' checkbox. This will then mean that images, text and videos can be
// unlocked in any of them". One box, the same on the Scenes, Images and Video tabs (Python: webui/tabs/image_sets.py
// set_unlock / publish_unlocks, namespace "imgsets"): each tick is one setting of the project. On the Images tab it
// also holds the Themes switch.
import { html, Check, tip, call } from "./ui.js";
import { useNs } from "./store.js";
import { ThemesSwitch } from "./image_sets.js";

const TIPS = {
  images: "Off: the original extracted pictures are locked (blue lock), and only pictures you replace can have the "
    + "individual files colour profile baked in. On: every picture gets a palette, on the Images tab and in Scenes. "
    + "It is staged from its original extracted copy when you build, so building again never corrects it twice. "
    + "Turning it off puts the extracted pictures back as they were.",
  videos: "Off: the game's own clips are locked, and only clips you replace can have the individual files colour "
    + "profile baked in. On: every clip gets a palette on the Video tab. Turning it off puts them back as they were.",
  text: "Off: the game's own lines of text are locked, and only lines you add in Scenes can have a colour profile. "
    + "On: every line of text in Scenes gets a palette. Turning it off locks them again; their switches come back "
    + "when it is ticked.",
};

export function UnlockBox({ themes = false }) {
  const sets = useNs("imgsets");
  const img = useNs("images");
  const vid = useNs("video");
  const u = sets.unlock || {};
  const imgOffered = !!(u.offered || (img.color_unlock && img.color_unlock.offered));
  const vidOffered = !!(u.videos_offered || vid.color_offered);
  if (!imgOffered && !vidOffered && !(themes && sets.on)) return null;
  const tick = (kind, label, on) => html`<span ...${tip(TIPS[kind])}><${Check} checked=${!!on} cls="small"
      label=${label} onChange=${(v) => call("imgsets.set_unlock", kind, v)} /></span>`;
  const any = (imgOffered && (u.images || u.text)) || (vidOffered && u.videos);
  return html`<div class=${`unlock-box${any ? " on" : ""}`}>
    <span class="look-head">Advanced</span>
    ${themes ? html`<${ThemesSwitch} />` : null}
    ${imgOffered ? tick("images", "Unlock extracted images", u.images) : null}
    ${vidOffered ? tick("videos", "Unlock extracted videos", u.videos) : null}
    ${imgOffered ? tick("text", "Unlock extracted text", u.text) : null}
  </div>`;
}
