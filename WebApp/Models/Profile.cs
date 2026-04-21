using Microsoft.AspNetCore.Http;
using System;

namespace WebApp.Models
{
    public class Profile
    {
        public int Id { get; set; }

        // =========================
        // USER INFORMATION
        // =========================
        public string FullName { get; set; } = string.Empty;

        public string Username { get; set; } = string.Empty;

        public string Email { get; set; } = string.Empty;

        public string Role { get; set; } = string.Empty;

        // =========================
        // SECURITY INFORMATION
        // =========================
        public string Status { get; set; } = "Active";

        public DateTime? LastLogin { get; set; }

        public DateTime? CreatedAt { get; set; }

        public DateTime? UpdatedAt { get; set; }

        // =========================
        // PROFILE IMAGE
        // =========================
        public string ProfileImagePath { get; set; } = "/images/default-profile.png";

        public IFormFile? ProfileImage { get; set; }

        // =========================
        // CONSTRUCTORS
        // =========================
        public Profile() { }

        public Profile(int id, string fullName, string username, string email, string role)
        {
            Id = id;
            FullName = fullName;
            Username = username;
            Email = email;
            Role = role;
        }
    }
}