import React from "react";
import { createRoot } from "react-dom/client";
import { BlackHoleAvatarEffect } from "./blackhole-avatar-effect";
import "./styles.css";

const mount = document.getElementById("blackhole-avatar-root");

if (mount) {
  const props = {
    profileImageUrl: mount.dataset.profileImage || "",
    profileInitial: mount.dataset.profileInitial || "?",
    displayName: mount.dataset.displayName || "",
    rankName: mount.dataset.rankName || "Gold",
    rankIconUrl: mount.dataset.rankIcon || "",
  };
  createRoot(mount).render(<BlackHoleAvatarEffect {...props} />);
}
