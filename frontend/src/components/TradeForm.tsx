import { Form, InputNumber, Input, Select, Button, message } from "antd";
import { apiPost } from "../api/client";

export function TradeForm({ accountId, onDone }:
  { accountId: number; onDone: () => void }) {
  const [form] = Form.useForm();
  async function submit(v: { code: string; side: string; price: number; shares: number }) {
    try {
      await apiPost("/api/trade", {
        account_id: accountId, code: v.code, side: v.side,
        price: v.price, shares: v.shares,
        on: new Date().toISOString().slice(0, 10),
      });
      message.success("成交");
      form.resetFields();
      onDone();
    } catch (e) {
      message.error("失败: " + (e as Error).message);
    }
  }
  return (
    <Form form={form} layout="inline" onFinish={submit}
          initialValues={{ code: "600519.SH", side: "BUY", price: 1500, shares: 100 }}>
      <Form.Item name="code" rules={[{ required: true }]}>
        <Input placeholder="代码 如 600519.SH" /></Form.Item>
      <Form.Item name="side"><Select style={{ width: 90 }}
        options={[{ value: "BUY", label: "买入" }, { value: "SELL", label: "卖出" }]} /></Form.Item>
      <Form.Item name="price" rules={[{ required: true }]}>
        <InputNumber placeholder="价格" min={0} /></Form.Item>
      <Form.Item name="shares" rules={[{ required: true }]}>
        <InputNumber placeholder="股数" min={0} step={100} /></Form.Item>
      <Form.Item><Button type="primary" htmlType="submit">下单</Button></Form.Item>
    </Form>
  );
}
