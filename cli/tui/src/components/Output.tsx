import React from "react";
import { Box, Text } from "ink";

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface Props {
  messages: Message[];
}

export default function Output({ messages }: Props) {
  return (
    <Box flexDirection="column">
      {messages.map((msg, i) => (
        <Box key={i} flexDirection="column">
          <Text bold color="cyan">{msg.role === "user" ? "You:" : "Assistant:"}</Text>
          <Text>{msg.content}</Text>
        </Box>
      ))}
    </Box>
  );
}