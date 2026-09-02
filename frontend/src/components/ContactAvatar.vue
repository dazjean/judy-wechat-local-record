<template>
  <span class="contact-avatar" :style="{ width: size + 'px', height: size + 'px' }">
    <img
      v-if="showImg"
      :src="src"
      alt=""
      class="avatar-img"
      @error="failed = true"
    />
    <span v-else class="avatar-initial">{{ initial }}</span>
  </span>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { contactAvatarUrl } from "../api";

const props = defineProps({
  contactId: { type: Number, default: 0 },
  name: { type: String, default: "" },
  hasAvatar: { type: Boolean, default: false },
  size: { type: Number, default: 32 },
});

const failed = ref(false);

watch(
  () => [props.contactId, props.hasAvatar],
  () => {
    failed.value = false;
  }
);

const src = computed(() => (props.contactId ? contactAvatarUrl(props.contactId) : ""));
const showImg = computed(() => props.hasAvatar && props.contactId && !failed.value);
const initial = computed(() => {
  const text = (props.name || "").trim();
  return text ? text[0] : "?";
});
</script>

<style scoped>
.contact-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  overflow: hidden;
  background: #eef2f7;
  color: #4a5568;
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
  vertical-align: middle;
}
.avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.avatar-initial {
  line-height: 1;
}
</style>
