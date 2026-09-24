FROM node:20-slim
WORKDIR /web
COPY package.json ./
RUN npm install
COPY . .
ARG NEXT_PUBLIC_API_URL
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]
