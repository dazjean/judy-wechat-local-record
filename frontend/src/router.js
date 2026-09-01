import { createRouter, createWebHistory } from "vue-router";
import MainLayout from "./layouts/MainLayout.vue";
import Dashboard from "./views/Dashboard.vue";
import Sync from "./views/Sync.vue";
import Conversations from "./views/Conversations.vue";
import Metrics from "./views/Metrics.vue";
import Analysis from "./views/Analysis.vue";
import Prompts from "./views/Prompts.vue";
import Groups from "./views/Groups.vue";
import Settings from "./views/Settings.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      component: MainLayout,
      children: [
        { path: "", name: "dashboard", component: Dashboard },
        { path: "sync", name: "sync", component: Sync },
        { path: "conversations", name: "conversations", component: Conversations },
        { path: "metrics", name: "metrics", component: Metrics },
        { path: "analysis", name: "analysis-index", component: Analysis },
        { path: "analysis/:promptId", name: "analysis", component: Analysis },
        { path: "groups", name: "groups", component: Groups },
        { path: "prompts", name: "prompts", component: Prompts },
        { path: "settings", name: "settings", component: Settings },
      ],
    },
  ],
});

export default router;
