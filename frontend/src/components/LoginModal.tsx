import { useState } from 'react';
import { Modal, Form, Input, message } from 'antd';
import { dockerLogin } from '../api/client';

interface Props {
  open: boolean;
  registry: string;
  onSuccess: () => void;
  onCancel: () => void;
}

export default function LoginModal({ open, registry, onSuccess, onCancel }: Props) {
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      const res = await dockerLogin(registry, values.username, values.password);
      if (res.success) {
        message.success('登录成功');
        form.resetFields();
        onSuccess();
      } else {
        message.error(`登录失败: ${res.message}`);
      }
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'response' in err) {
        message.error('登录请求失败');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={`登录镜像仓库 - ${registry}`}
      open={open}
      onOk={handleOk}
      onCancel={onCancel}
      confirmLoading={loading}
      okText="登录"
      cancelText="取消"
    >
      <Form form={form} layout="vertical">
        <Form.Item label="用户名" name="username" rules={[{ required: true, message: '请输入用户名' }]}>
          <Input placeholder="请输入用户名" />
        </Form.Item>
        <Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }]}>
          <Input.Password placeholder="请输入密码" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
