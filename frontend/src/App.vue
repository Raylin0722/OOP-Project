<script setup>
import { onBeforeUnmount, onMounted } from 'vue';
import { startSessionTimeoutWatcher, stopSessionTimeoutWatcher } from './sessionTimeout.js';

onMounted(() => {
  startSessionTimeoutWatcher();
});

onBeforeUnmount(() => {
  stopSessionTimeoutWatcher();
});
</script>

<template>
  <router-view></router-view>
</template>
