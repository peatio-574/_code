<script setup lang="ts">
// 个人中心：修改姓名/手机号/头像与修改密码。
import { Lock, User } from '@element-plus/icons-vue'
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { changePassword, updateProfile } from '@/api/auth'
import { api, errorMessage } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const profile = reactive({
  display_name: auth.user?.display_name ?? '',
  mobile: auth.user?.mobile ?? '',
  avatar: auth.user?.avatar ?? '',
})

const password = reactive({ old_password: '', new_password: '', confirm_password: '' })

const savingProfile = ref(false)
const savingPassword = ref(false)

async function uploadAvatar(options: any) {
  const form = new FormData()
  form.append('file', options.file)
  try {
    const response = await api.post('/api/file/upload', form, { headers: { 'Content-Type': 'multipart/form-data' } })
    const id = response.data?.data?.id
    if (id) {
      profile.avatar = id
      ElMessage.success('头像上传成功')
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function saveProfile() {
  savingProfile.value = true
  try {
    const result = await updateProfile(profile)
    if (result.success) {
      await auth.loadSelf()
      ElMessage.success('资料已保存')
    } else {
      ElMessage.error(result.message || '保存失败')
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    savingProfile.value = false
  }
}

async function savePassword() {
  if (!password.old_password || !password.new_password) {
    ElMessage.warning('请填写完整')
    return
  }
  if (password.new_password !== password.confirm_password) {
    ElMessage.error('两次输入的密码不一致')
    return
  }
  savingPassword.value = true
  try {
    const result = await changePassword(password)
    if (result.success) {
      ElMessage.success('密码已修改，请重新登录')
      await auth.logout()
      window.location.href = '/login'
    } else {
      ElMessage.error(result.message || '修改失败')
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    savingPassword.value = false
  }
}
</script>

<template>
  <div class="profile">
    <header class="data-page__header">
      <div>
        <h1 class="data-page__title">个人中心</h1>
        <p class="data-page__desc">管理你的账号资料与登录密码。</p>
      </div>
    </header>

    <div class="profile__grid">
      <section class="panel">
        <div class="panel__head">
          <h2 class="panel__title"><el-icon><User /></el-icon>个人信息</h2>
        </div>
        <el-form label-width="80px" class="panel__form">
          <el-form-item label="头像">
            <el-upload :show-file-list="false" :before-upload="() => false" :http-request="uploadAvatar">
              <div class="avatar-upload">
                <el-avatar :size="72" :src="profile.avatar ? `/api/image/${profile.avatar}` : undefined">
                  {{ (profile.display_name || auth.user?.username || 'U')[0] }}
                </el-avatar>
                <span class="avatar-upload__hint">点击更换</span>
              </div>
            </el-upload>
          </el-form-item>
          <el-form-item label="姓名">
            <el-input v-model="profile.display_name" placeholder="请输入姓名" />
          </el-form-item>
          <el-form-item label="手机号">
            <el-input v-model="profile.mobile" placeholder="请输入手机号" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="savingProfile" @click="saveProfile">保存资料</el-button>
          </el-form-item>
        </el-form>
      </section>

      <section class="panel">
        <div class="panel__head">
          <h2 class="panel__title"><el-icon><Lock /></el-icon>修改密码</h2>
        </div>
        <el-form label-width="80px" class="panel__form">
          <el-form-item label="原密码">
            <el-input v-model="password.old_password" type="password" show-password placeholder="请输入原密码" />
          </el-form-item>
          <el-form-item label="新密码">
            <el-input v-model="password.new_password" type="password" show-password placeholder="请输入新密码" />
          </el-form-item>
          <el-form-item label="确认密码">
            <el-input v-model="password.confirm_password" type="password" show-password placeholder="请再次输入新密码" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="savingPassword" @click="savePassword">修改密码</el-button>
          </el-form-item>
        </el-form>
      </section>
    </div>
  </div>
</template>

<style scoped>
.profile {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
.profile__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-5);
  align-items: start;
}
.panel {
  padding: var(--space-5);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}
.panel__head {
  margin-bottom: var(--space-5);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--border-color);
}
.panel__title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-lg);
  font-weight: 700;
}
.panel__form {
  max-width: 420px;
}
.avatar-upload {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
}
.avatar-upload__hint {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.avatar-upload:hover .avatar-upload__hint {
  color: var(--brand-500);
}

@media (max-width: 860px) {
  .profile__grid {
    grid-template-columns: 1fr;
  }
}
</style>
