import React from "react";
import { createRoot } from "react-dom/client";
import { BlackHoleProfileHero } from "./blackhole-profile-hero";
import "./styles.css";

const mount = document.getElementById("blackhole-profile-root");

if (mount) {
  const props = {
    profileImageUrl: mount.dataset.profileImage || "",
    profileInitial: mount.dataset.profileInitial || "?",
    displayName: mount.dataset.displayName || "",
    rankName: mount.dataset.rankName || "Gold",
    rankDescription: mount.dataset.rankDescription || "",
    rankIconUrl: mount.dataset.rankIcon || "",
  };
  createRoot(mount).render(<BlackHoleProfileHero {...props} />);
}
