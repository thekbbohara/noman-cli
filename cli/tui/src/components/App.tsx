import React, { useState } from "react";
import { Box } from "ink";
import Input from "./Input.js";
import Output from "./Output.js";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (text: string) => {
    setMessages(prev => [...prev, { role: "user", content: text }]);
    setIsLoading(true);

    const response = await fetch("/dev/stdin", {
      method: "POST",
      body: JSON.stringify({ method: "chat", params: { message: text }, id: 1 }),
    });
    const data = await response.json();

    setMessages(prev => [...prev, { role: "assistant", content: data.result?.response ?? "" }]);
    setIsLoading(false);
  };

  return (
    <Box flexDirection="column" height={process.stdout.rows - 1}>
      <Box flexDirection="column" borderStyle="round" borderColor="green" padding={1}>
        <Output messages={messages} />
      </Box>
      <Input onSubmit={handleSubmit} isLoading={isLoading} />
    </Box>
  );
}